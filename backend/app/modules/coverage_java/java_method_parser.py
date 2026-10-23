"""
Java 方法解析器：提取方法单元和指纹

解析策略：
- 使用 javalang 提取方法起始行
- 用括号匹配算法（跳过字符串、字符字面量、注释、文本块）精确定位结束行
- 为每个方法计算指纹（方法范围内每行 strip 后用 \n 连接取 SHA-1）
- 支持普通方法、构造器、重载、内部类、静态块、字段初始化
- 匿名类和 lambda 归外层方法；具名内部类单独成单元
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional
import javalang

_TEXT_BLOCK_RE = re.compile(r'"""[\s\S]*?(?<!\\)"""')


@dataclass
class MethodUnit:
    """方法单元
    
    key: FQN#name(paramTypes) 或伪单元 <init-fields>、<clinit>
    start/end: 起止行号（1-based），伪单元无 start/end
    lines: 伪单元的行号列表
    fingerprint: 方法范围内每行 strip 后连接的 SHA-1
    """
    key: str
    fingerprint: str
    start: Optional[int] = None
    end: Optional[int] = None
    lines: Optional[List[int]] = None


class JavaMethodParser:
    """Java 方法解析器"""
    
    def parse_file(self, source_code: str, file_path: str) -> Optional[List[MethodUnit]]:
        """解析单个 Java 文件
        
        Args:
            source_code: Java 源码
            file_path: 文件路径（用于构造 FQN），形如 com/example/Foo.java
        
        Returns:
            方法单元列表，解析失败返回 None（降级为文件级保留）
        """
        try:
            # javalang 0.13 不支持文本块，替换为保留换行的空字符串，行号不变
            parse_source = _TEXT_BLOCK_RE.sub(
                lambda m: '""' + "\n" * m.group(0).count("\n"), source_code
            )
            tree = javalang.parse.parse(parse_source)
            lines = source_code.splitlines()

            # javalang 中初始化块是无 position 的 list，用 token 定位 `static {`
            static_starts = self._find_static_block_lines(parse_source)
            static_iter = iter(static_starts)
            init_block_count = 0
            
            # 提取包名和类名
            package = tree.package.name if tree.package else ""
            
            # 从文件路径提取预期类名（不依赖 tree.types，因为可能有多个类）
            # file_path = com/example/Foo.java -> expected_class = Foo
            expected_class = file_path.split("/")[-1].replace(".java", "")
            
            units = []
            
            # 递归遍历所有类型声明（包括嵌套类）
            def visit_type(type_node, parent_fqn: str = ""):
                # 构造当前类的 FQN
                if parent_fqn:
                    fqn = f"{parent_fqn}.{type_node.name}"
                else:
                    fqn = f"{package}.{type_node.name}" if package else type_node.name
                
                # 解析该类的字段初始化
                field_lines = self._extract_field_init_lines(type_node, lines)
                if field_lines:
                    fp = self._compute_fingerprint(lines, field_lines=field_lines)
                    units.append(MethodUnit(
                        key=f"{fqn}#<init-fields>",
                        fingerprint=fp,
                        lines=field_lines
                    ))
                
                # 解析方法、构造器、静态块
                for member in type_node.body or []:
                    if isinstance(member, (javalang.tree.MethodDeclaration, javalang.tree.ConstructorDeclaration)):
                        method_unit = self._parse_method(member, fqn, lines)
                        if method_unit:
                            units.append(method_unit)
                    
                    # 静态块
                    elif isinstance(member, list):
                        nonlocal init_block_count
                        init_block_count += 1
                        start = next(static_iter, None)
                        if start:
                            end = self._find_block_end(lines, start - 1)
                            if end:
                                fp = self._compute_fingerprint(lines, start, end)
                                units.append(MethodUnit(
                                    key=f"{fqn}#<clinit>",
                                    fingerprint=fp,
                                    start=start,
                                    end=end
                                ))
                    
                    # 递归处理嵌套类
                    elif isinstance(member, javalang.tree.TypeDeclaration):
                        visit_type(member, fqn)
            
            # 遍历顶层类型
            for type_decl in tree.types:
                visit_type(type_decl)
            
            # 存在实例初始化块时无法与 static 块一一对应，降级为文件级
            if init_block_count != len(static_starts):
                return None

            # 自检：方法范围不应交叉
            if not self._validate_no_overlap(units):
                return None
            
            return units
            
        except Exception:
            # 解析失败降级为文件级
            return None
    
    def _find_static_block_lines(self, source: str) -> List[int]:
        """按源码顺序返回所有 `static {` 的起始行号"""
        tokens = list(javalang.tokenizer.tokenize(source))
        result = []
        for prev, tok in zip(tokens, tokens[1:]):
            if prev.value == "static" and tok.value == "{":
                result.append(prev.position.line)
        return result

    def _parse_method(self, node, fqn: str, lines: List[str]) -> Optional[MethodUnit]:
        """解析单个方法或构造器"""
        if not node.position:
            return None
        
        start = node.position.line
        
        # 构造方法 key: FQN#name(paramTypes)
        if isinstance(node, javalang.tree.ConstructorDeclaration):
            method_name = "<init>"
        else:
            method_name = node.name
        
        # 参数类型列表
        param_types = []
        if node.parameters:
            for param in node.parameters:
                param_types.append(self._type_to_string(param.type))
        
        key = f"{fqn}#{method_name}({','.join(param_types)})"
        
        # 用括号匹配找结束行
        end = self._find_block_end(lines, start - 1)
        if not end:
            return None
        
        fp = self._compute_fingerprint(lines, start, end)
        
        return MethodUnit(key=key, fingerprint=fp, start=start, end=end)
    
    def _find_block_end(self, lines: List[str], start_line_idx: int) -> Optional[int]:
        """找到方法体结束行（括号匹配，跳过字符串、注释、文本块）
        
        Args:
            lines: 源码行列表（0-based）
            start_line_idx: 方法起始行索引（0-based）
        
        Returns:
            结束行号（1-based），找不到返回 None
        """
        # 从 start_line_idx 开始找第一个 {
        brace_depth = 0
        found_open = False
        in_string = False
        in_char = False
        in_comment = False
        in_text_block = False
        escape_next = False
        
        i = start_line_idx
        while i < len(lines):
            line = lines[i]
            j = 0
            while j < len(line):
                char = line[j]
                
                # 文本块（Java 13+）
                if not in_string and not in_char and not in_comment:
                    if j + 2 < len(line) and line[j:j+3] == '"""':
                        in_text_block = not in_text_block
                        j += 3
                        continue
                
                if in_text_block:
                    j += 1
                    continue
                
                # 单行注释
                if not in_string and not in_char and not in_comment:
                    if j + 1 < len(line) and line[j:j+2] == '//':
                        break  # 跳到下一行
                
                # 多行注释
                if not in_string and not in_char:
                    if not in_comment and j + 1 < len(line) and line[j:j+2] == '/*':
                        in_comment = True
                        j += 2
                        continue
                    if in_comment and j + 1 < len(line) and line[j:j+2] == '*/':
                        in_comment = False
                        j += 2
                        continue
                
                if in_comment:
                    j += 1
                    continue
                
                # 字符串
                if not in_char and char == '"' and not escape_next:
                    in_string = not in_string
                    j += 1
                    continue
                
                # 字符字面量
                if not in_string and char == "'" and not escape_next:
                    in_char = not in_char
                    j += 1
                    continue
                
                # 转义
                if (in_string or in_char) and char == '\\' and not escape_next:
                    escape_next = True
                    j += 1
                    continue
                
                if escape_next:
                    escape_next = False
                    j += 1
                    continue
                
                # 括号匹配
                if not in_string and not in_char:
                    if char == '{':
                        brace_depth += 1
                        found_open = True
                    elif char == '}':
                        brace_depth -= 1
                        if brace_depth == 0 and found_open:
                            return i + 1  # 返回 1-based 行号
                
                j += 1
            
            i += 1
        
        return None
    
    def _extract_field_init_lines(self, type_node, lines: List[str]) -> List[int]:
        """提取字段初始化行（有初始值的字段声明）"""
        field_lines = []
        for member in type_node.body or []:
            if isinstance(member, javalang.tree.FieldDeclaration):
                # 检查是否有初始化
                for declarator in member.declarators:
                    if declarator.initializer and member.position:
                        field_lines.append(member.position.line)
                        break
        return sorted(set(field_lines))
    
    def _compute_fingerprint(self, lines: List[str], start: Optional[int] = None, 
                           end: Optional[int] = None, field_lines: Optional[List[int]] = None) -> str:
        """计算方法指纹（范围内每行 strip 后用 \n 连接取 SHA-1）"""
        content_lines = []
        
        if field_lines:
            for line_no in field_lines:
                content_lines.append(lines[line_no - 1].strip())
        else:
            for line_no in range(start, end + 1):
                content_lines.append(lines[line_no - 1].strip())
        
        content = "\n".join(content_lines)
        return hashlib.sha1(content.encode('utf-8')).hexdigest()
    
    def _type_to_string(self, type_node) -> str:
        """将 javalang 类型节点转为字符串"""
        if isinstance(type_node, javalang.tree.BasicType):
            return type_node.name
        elif isinstance(type_node, javalang.tree.ReferenceType):
            name = type_node.name
            # 处理泛型
            if type_node.arguments:
                args = ",".join(self._type_to_string(arg.type) if hasattr(arg, 'type') else str(arg) 
                               for arg in type_node.arguments)
                name += f"<{args}>"
            # 处理数组
            if type_node.dimensions:
                name += "[]" * len(type_node.dimensions)
            return name
        else:
            return str(type_node)
    
    def _validate_no_overlap(self, units: List[MethodUnit]) -> bool:
        """验证方法范围不交叉（自检）"""
        ranges = [(u.start, u.end) for u in units if u.start and u.end]
        ranges.sort()
        
        for i in range(len(ranges) - 1):
            if ranges[i][1] >= ranges[i+1][0]:
                return False
        
        return True


def parse_java_file(source_code: str, file_path: str) -> Optional[List[MethodUnit]]:
    """便捷函数：解析 Java 文件"""
    parser = JavaMethodParser()
    return parser.parse_file(source_code, file_path)
