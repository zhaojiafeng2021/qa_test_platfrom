"""
账本合并器：合并 exec 报告行与迁移行

合并规则：
1. exec 行优先（精确来源）
2. exec missed + 迁移 covered → 取 inherited
3. 两者都有覆盖 → 逐字段取 max，sources 取并集
4. 幂等性：多次合并结果相同
"""

from dataclasses import dataclass
from typing import Dict, List
from app.modules.coverage_java.ledger_migrator import LineCoverage


@dataclass
class FileCoverage:
    """文件覆盖汇总"""
    file_path: str
    lines: Dict[int, LineCoverage]
    lines_covered: int = 0
    lines_total: int = 0
    line_rate: float = 0.0


@dataclass
class LedgerSummary:
    """账本汇总统计"""
    lines_covered: int = 0
    lines_total: int = 0
    line_rate: float = 0.0
    branches_covered: int = 0
    branches_total: int = 0
    branch_rate: float = 0.0
    
    # 按来源拆分的统计
    unittest_lines: int = 0
    runtime_lines: int = 0
    inherited_lines: int = 0


class LedgerMerger:
    """账本合并器"""
    
    def merge_file(
        self,
        exec_lines: Dict[int, LineCoverage],
        migrated_lines: Dict[int, LineCoverage]
    ) -> Dict[int, LineCoverage]:
        """合并单个文件的覆盖数据
        
        Args:
            exec_lines: exec 报告的行数据
            migrated_lines: 迁移的行数据
        
        Returns:
            合并后的行数据
        """
        merged: Dict[int, LineCoverage] = {}
        
        # 所有行号
        all_lines = set(exec_lines.keys()) | set(migrated_lines.keys())
        
        for line_no in all_lines:
            exec_cov = exec_lines.get(line_no)
            migrated_cov = migrated_lines.get(line_no)
            
            if exec_cov and migrated_cov:
                # 两者都有：合并
                merged[line_no] = self._merge_line(exec_cov, migrated_cov)
            elif exec_cov:
                # 只有 exec：直接采用
                merged[line_no] = exec_cov
            elif migrated_cov:
                # 只有迁移：采用迁移（exec 中字节码变化的类）
                merged[line_no] = migrated_cov
        
        return merged
    
    def _merge_line(self, exec_cov: LineCoverage, migrated_cov: LineCoverage) -> LineCoverage:
        """合并单行覆盖数据
        
        规则：
        - exec covered/partial → 采用 exec（精确）
        - exec missed + migrated covered → 采用 inherited
        - 逐字段取 max，sources 取并集
        """
        # exec 优先（非 missed）
        if exec_cov.status in ["covered", "partial"]:
            # 指令 / 分支总数以 exec（目标 commit 的字节码）为准，covered 取 max，missed = 总数 - covered，
            # 避免两边各取 max 导致总数膨胀
            branch_total = exec_cov.cb + exec_cov.mb
            merged_cb = min(branch_total, max(exec_cov.cb, migrated_cov.cb))
            merged_mb = branch_total - merged_cb
            insn_total = exec_cov.ci + exec_cov.mi
            merged_ci = min(insn_total, max(exec_cov.ci, migrated_cov.ci))

            status = "partial" if merged_mb > 0 or merged_ci < insn_total else "covered"

            return LineCoverage(
                line_no=exec_cov.line_no,
                ci=merged_ci,
                mi=insn_total - merged_ci,
                cb=merged_cb,
                mb=merged_mb,
                status=status,
                sources=self._merge_sources(exec_cov.sources, migrated_cov.sources)
            )
        
        # exec missed，检查迁移
        if migrated_cov.status in ["covered", "partial"]:
            # 迁移有覆盖，采用 inherited
            return LineCoverage(
                line_no=exec_cov.line_no,
                ci=migrated_cov.ci,
                mi=migrated_cov.mi,
                cb=migrated_cov.cb,
                mb=migrated_cov.mb,
                status=migrated_cov.status,
                sources=["inherited"]
            )
        
        # 都是 missed
        return LineCoverage(
            line_no=exec_cov.line_no,
            ci=0,
            mi=max(exec_cov.mi, migrated_cov.mi),
            cb=0,
            mb=max(exec_cov.mb, migrated_cov.mb),
            status="missed",
            sources=[]
        )

    def _merge_sources(self, sources1: List[str], sources2: List[str]) -> List[str]:
        """合并来源列表：取并集并去重"""
        return sorted(set(sources1 + sources2))
    
    def compute_file_summary(self, lines: Dict[int, LineCoverage]) -> tuple[int, int, float]:
        """计算文件级汇总
        
        Returns:
            (lines_covered, lines_total, line_rate)
        """
        if not lines:
            return 0, 0, 0.0
        
        covered = sum(1 for cov in lines.values() if cov.status in ["covered", "partial"])
        total = len(lines)
        rate = covered / total if total > 0 else 0.0
        
        return covered, total, rate
    
    def compute_ledger_summary(self, files: Dict[str, Dict[int, LineCoverage]]) -> LedgerSummary:
        """计算账本汇总统计
        
        Args:
            files: {file_path: {line_no: LineCoverage}}
        
        Returns:
            账本汇总
        """
        summary = LedgerSummary()
        
        all_lines = []
        for file_lines in files.values():
            all_lines.extend(file_lines.values())
        
        if not all_lines:
            return summary
        
        # 行覆盖率
        summary.lines_total = len(all_lines)
        summary.lines_covered = sum(1 for cov in all_lines if cov.status in ["covered", "partial"])
        summary.line_rate = summary.lines_covered / summary.lines_total if summary.lines_total > 0 else 0.0
        
        # 分支覆盖率
        for cov in all_lines:
            summary.branches_covered += cov.cb
            summary.branches_total += cov.cb + cov.mb
        
        summary.branch_rate = (summary.branches_covered / summary.branches_total 
                              if summary.branches_total > 0 else 0.0)
        
        # 按来源统计（一行可能有多个来源）
        for cov in all_lines:
            if cov.status not in ["covered", "partial"]:
                continue
            
            if "unittest" in cov.sources:
                summary.unittest_lines += 1
            if "runtime" in cov.sources:
                summary.runtime_lines += 1
            if "inherited" in cov.sources and len(cov.sources) == 1:
                # 仅继承（没有实测）
                summary.inherited_lines += 1
        
        return summary
    
    def is_idempotent(
        self,
        lines1: Dict[int, LineCoverage],
        lines2: Dict[int, LineCoverage]
    ) -> bool:
        """验证幂等性：两次合并结果应相同"""
        if set(lines1.keys()) != set(lines2.keys()):
            return False
        
        for line_no in lines1:
            cov1 = lines1[line_no]
            cov2 = lines2[line_no]
            
            if (cov1.ci != cov2.ci or cov1.mi != cov2.mi or
                cov1.cb != cov2.cb or cov1.mb != cov2.mb or
                cov1.status != cov2.status or
                sorted(cov1.sources) != sorted(cov2.sources)):
                return False
        
        return True


def merge_file(
    exec_lines: Dict[int, LineCoverage],
    migrated_lines: Dict[int, LineCoverage]
) -> Dict[int, LineCoverage]:
    """便捷函数：合并文件覆盖"""
    merger = LedgerMerger()
    return merger.merge_file(exec_lines, migrated_lines)


def compute_summary(files: Dict[str, Dict[int, LineCoverage]]) -> LedgerSummary:
    """便捷函数：计算汇总"""
    merger = LedgerMerger()
    return merger.compute_ledger_summary(files)
