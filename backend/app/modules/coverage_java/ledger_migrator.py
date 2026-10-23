"""
账本迁移器：方法级覆盖率迁移

迁移规则：
- 指纹相同：保留覆盖并偏移行号
- 指纹不同：整个方法清零
- 已删除：丢弃
- 新增：全部未覆盖

不在任何方法单元中的行不迁移
"""

from dataclasses import dataclass
from typing import Dict, List, Set
from app.modules.coverage_java.java_method_parser import MethodUnit


@dataclass
class LineCoverage:
    """行覆盖数据"""
    line_no: int
    ci: int = 0  # covered instructions
    mi: int = 0  # missed instructions
    cb: int = 0  # covered branches
    mb: int = 0  # missed branches
    status: str = "missed"  # covered / partial / missed
    sources: List[str] = None  # 来源列表
    
    def __post_init__(self):
        if self.sources is None:
            self.sources = []


@dataclass
class MigrationStats:
    """迁移统计"""
    methods_kept: int = 0      # 保留并偏移
    methods_reset: int = 0     # 清零
    methods_removed: int = 0   # 删除
    methods_added: int = 0     # 新增
    reset_methods: List[str] = None  # 被清零方法的 key 列表
    
    def __post_init__(self):
        if self.reset_methods is None:
            self.reset_methods = []


class LedgerMigrator:
    """账本迁移器"""
    
    def migrate(
        self,
        old_units: List[MethodUnit],
        new_units: List[MethodUnit],
        old_coverage: Dict[int, LineCoverage],
        exclude_classes: Set[str] = None,
        keep_sources: bool = False,
    ) -> tuple[Dict[int, LineCoverage], MigrationStats]:
        """迁移方法级覆盖率
        
        Args:
            old_units: 旧 commit 的方法单元列表
            new_units: 新 commit 的方法单元列表
            old_coverage: 旧账本的行覆盖数据 {line_no: LineCoverage}
            exclude_classes: 要排除的类（JaCoCo class 不一致的类）
            keep_sources: 保留行原有 sources（账本编排用，由上层决定是否标记 inherited）
        
        Returns:
            (迁移后的行覆盖数据, 迁移统计)
        """
        if exclude_classes is None:
            exclude_classes = set()
        self._keep_sources = keep_sources
        
        # 构建旧方法索引 {key: unit}
        old_index = {u.key: u for u in old_units}
        
        # 新方法按 key 分组
        new_index = {u.key: u for u in new_units}
        
        migrated_coverage: Dict[int, LineCoverage] = {}
        stats = MigrationStats()
        
        # 遍历新方法
        for new_unit in new_units:
            # 检查是否在排除列表中（根据 FQN 前缀匹配类名）
            class_fqn = new_unit.key.split("#")[0]
            if any(class_fqn == excluded or class_fqn.startswith(excluded + "$") 
                   for excluded in exclude_classes):
                # 该类不一致，跳过迁移
                continue
            
            if new_unit.key in old_index:
                old_unit = old_index[new_unit.key]
                
                # 指纹相同：保留并偏移
                if old_unit.fingerprint == new_unit.fingerprint:
                    self._migrate_method_kept(old_unit, new_unit, old_coverage, migrated_coverage)
                    stats.methods_kept += 1
                else:
                    # 指纹不同：清零
                    self._migrate_method_reset(new_unit, migrated_coverage)
                    stats.methods_reset += 1
                    stats.reset_methods.append(new_unit.key)
            else:
                # 新增方法：全部未覆盖
                self._migrate_method_added(new_unit, migrated_coverage)
                stats.methods_added += 1
        
        # 统计删除的方法
        for old_key in old_index:
            if old_key not in new_index:
                class_fqn = old_key.split("#")[0]
                # 只统计非排除类的删除
                if not any(class_fqn == excluded or class_fqn.startswith(excluded + "$") 
                          for excluded in exclude_classes):
                    stats.methods_removed += 1
        
        return migrated_coverage, stats
    
    def _migrate_method_kept(
        self,
        old_unit: MethodUnit,
        new_unit: MethodUnit,
        old_coverage: Dict[int, LineCoverage],
        migrated_coverage: Dict[int, LineCoverage]
    ):
        """迁移保留的方法：行号偏移"""
        # 伪单元（<init-fields>、<clinit>）用 lines 列表
        if old_unit.lines and new_unit.lines:
            # 按索引位置对应
            for i, old_line in enumerate(old_unit.lines):
                if i < len(new_unit.lines) and old_line in old_coverage:
                    new_line = new_unit.lines[i]
                    migrated_coverage[new_line] = self._moved(old_coverage[old_line], new_line)
        else:
            # 普通方法：计算偏移
            if old_unit.start and old_unit.end and new_unit.start and new_unit.end:
                offset = new_unit.start - old_unit.start
                
                for old_line in range(old_unit.start, old_unit.end + 1):
                    if old_line in old_coverage:
                        new_line = old_line + offset
                        migrated_coverage[new_line] = self._moved(old_coverage[old_line], new_line)

    def _moved(self, cov: LineCoverage, new_line: int) -> LineCoverage:
        sources = list(cov.sources) if getattr(self, "_keep_sources", False) else ["inherited"]
        return LineCoverage(
            line_no=new_line, ci=cov.ci, mi=cov.mi, cb=cov.cb, mb=cov.mb,
            status=cov.status, sources=sources,
        )
    
    def _migrate_method_reset(self, new_unit: MethodUnit, migrated_coverage: Dict[int, LineCoverage]):
        """迁移被修改的方法：清零"""
        if new_unit.lines:
            for line in new_unit.lines:
                migrated_coverage[line] = LineCoverage(
                    line_no=line,
                    status="missed",
                    sources=[]
                )
        else:
            if new_unit.start and new_unit.end:
                for line in range(new_unit.start, new_unit.end + 1):
                    migrated_coverage[line] = LineCoverage(
                        line_no=line,
                        status="missed",
                        sources=[]
                    )
    
    def _migrate_method_added(self, new_unit: MethodUnit, migrated_coverage: Dict[int, LineCoverage]):
        """迁移新增方法：全部未覆盖"""
        # 与 reset 逻辑相同
        self._migrate_method_reset(new_unit, migrated_coverage)


def migrate_ledger(
    old_units: List[MethodUnit],
    new_units: List[MethodUnit],
    old_coverage: Dict[int, LineCoverage],
    exclude_classes: Set[str] = None
) -> tuple[Dict[int, LineCoverage], MigrationStats]:
    """便捷函数：迁移账本"""
    migrator = LedgerMigrator()
    return migrator.migrate(old_units, new_units, old_coverage, exclude_classes)
