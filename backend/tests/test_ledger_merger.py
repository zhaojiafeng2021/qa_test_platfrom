"""测试账本合并器"""

import pytest
from app.modules.coverage_java.ledger_migrator import LineCoverage
from app.modules.coverage_java.ledger_merger import LedgerMerger, LedgerSummary


class TestLedgerMerger:
    """账本合并器测试"""
    
    def test_exec_priority_covered(self):
        """测试 exec covered 优先"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=3, status="covered", sources=["runtime"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # exec 优先，但取 max
        assert merged[10].ci == 3
        assert merged[10].status == "covered"
        assert "runtime" in merged[10].sources
        assert "inherited" in merged[10].sources
    
    def test_exec_missed_migrated_covered(self):
        """测试 exec missed + 迁移 covered → inherited"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=0, mi=2, status="missed", sources=[]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=3, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 采用迁移的覆盖
        assert merged[10].ci == 3
        assert merged[10].status == "covered"
        assert merged[10].sources == ["inherited"]
    
    def test_both_missed(self):
        """测试两者都 missed"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=0, mi=2, status="missed", sources=[]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=0, mi=2, status="missed", sources=[]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        assert merged[10].status == "missed"
        assert merged[10].ci == 0
        assert merged[10].mi == 2
    
    def test_branch_coverage_max(self):
        """测试分支覆盖取 max"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=2, cb=1, mb=1, status="partial", sources=["unittest"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=2, cb=2, mb=0, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 分支总数以 exec 为准（2），covered 取 max → 全覆盖，总数不膨胀
        assert merged[10].cb == 2
        assert merged[10].mb == 0
        assert merged[10].status == "covered"
    
    def test_sources_union(self):
        """测试 sources 取并集"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["unittest"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["inherited", "runtime"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 并集并排序
        assert sorted(merged[10].sources) == ["inherited", "runtime", "unittest"]
    
    def test_only_exec_line(self):
        """测试只有 exec 的行"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["runtime"]),
        }
        
        migrated_lines = {}
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 直接采用 exec
        assert 10 in merged
        assert merged[10].ci == 2
        assert merged[10].sources == ["runtime"]
    
    def test_only_migrated_line(self):
        """测试只有迁移的行（字节码变化的类）"""
        exec_lines = {}
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 采用迁移
        assert 10 in merged
        assert merged[10].ci == 2
        assert merged[10].sources == ["inherited"]
    
    def test_file_summary(self):
        """测试文件级汇总"""
        lines = {
            10: LineCoverage(line_no=10, status="covered"),
            11: LineCoverage(line_no=11, status="covered"),
            12: LineCoverage(line_no=12, status="partial"),
            13: LineCoverage(line_no=13, status="missed"),
        }
        
        merger = LedgerMerger()
        covered, total, rate = merger.compute_file_summary(lines)
        
        assert covered == 3  # covered + partial
        assert total == 4
        assert rate == 0.75
    
    def test_ledger_summary(self):
        """测试账本汇总统计"""
        files = {
            "A.java": {
                10: LineCoverage(line_no=10, ci=2, cb=1, mb=0, status="covered", sources=["unittest"]),
                11: LineCoverage(line_no=11, ci=3, cb=0, mb=1, status="partial", sources=["runtime"]),
                12: LineCoverage(line_no=12, ci=0, mi=2, cb=0, mb=0, status="missed", sources=[]),
            },
            "B.java": {
                20: LineCoverage(line_no=20, ci=1, cb=0, mb=0, status="covered", sources=["inherited"]),
            },
        }
        
        merger = LedgerMerger()
        summary = merger.compute_ledger_summary(files)
        
        # 行覆盖
        assert summary.lines_total == 4
        assert summary.lines_covered == 3
        assert summary.line_rate == 0.75
        
        # 分支覆盖
        assert summary.branches_covered == 1
        assert summary.branches_total == 2
        assert summary.branch_rate == 0.5
        
        # 按来源统计
        assert summary.unittest_lines == 1
        assert summary.runtime_lines == 1
        assert summary.inherited_lines == 1  # 仅继承
    
    def test_source_overlap_not_double_counted(self):
        """测试多来源的行不重复计数"""
        files = {
            "A.java": {
                10: LineCoverage(line_no=10, ci=2, status="covered", sources=["unittest", "runtime"]),
            },
        }
        
        merger = LedgerMerger()
        summary = merger.compute_ledger_summary(files)
        
        # 同时计入两个来源
        assert summary.unittest_lines == 1
        assert summary.runtime_lines == 1
        assert summary.inherited_lines == 0
    
    def test_inherited_with_test_not_counted_as_inherited_only(self):
        """测试 inherited + 实测不计入仅继承"""
        files = {
            "A.java": {
                10: LineCoverage(line_no=10, ci=2, status="covered", sources=["inherited", "unittest"]),
            },
        }
        
        merger = LedgerMerger()
        summary = merger.compute_ledger_summary(files)
        
        # 有实测来源，不算仅继承
        assert summary.unittest_lines == 1
        assert summary.inherited_lines == 0
    
    def test_idempotent_merge(self):
        """测试幂等性：多次合并结果相同"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["runtime"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=1, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        
        # 第一次合并
        merged1 = merger.merge_file(exec_lines, migrated_lines)
        
        # 第二次合并（用第一次结果再合并）
        merged2 = merger.merge_file(merged1, migrated_lines)
        
        # 结果应相同
        assert merger.is_idempotent(merged1, merged2)
    
    def test_idempotent_with_empty(self):
        """测试与空数据合并的幂等性"""
        lines = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["runtime"]),
        }
        
        empty = {}
        
        merger = LedgerMerger()
        merged1 = merger.merge_file(lines, empty)
        merged2 = merger.merge_file(merged1, empty)
        
        assert merger.is_idempotent(merged1, merged2)
    
    def test_partial_status_with_branches(self):
        """测试有未覆盖分支时状态为 partial"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=2, cb=1, mb=1, status="partial", sources=["unittest"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=2, cb=0, mb=0, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # 有未覆盖分支，状态为 partial
        assert merged[10].status == "partial"
        assert merged[10].mb == 1
    
    def test_empty_files(self):
        """测试空文件汇总"""
        merger = LedgerMerger()
        summary = merger.compute_ledger_summary({})
        
        assert summary.lines_total == 0
        assert summary.lines_covered == 0
        assert summary.line_rate == 0.0
    
    def test_merge_multiple_files(self):
        """测试合并多个文件"""
        exec_file1 = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["runtime"]),
        }
        migrated_file1 = {
            10: LineCoverage(line_no=10, ci=1, status="covered", sources=["inherited"]),
            11: LineCoverage(line_no=11, ci=0, mi=2, status="missed", sources=[]),
        }
        
        exec_file2 = {
            20: LineCoverage(line_no=20, ci=3, status="covered", sources=["unittest"]),
        }
        migrated_file2 = {}
        
        merger = LedgerMerger()
        merged1 = merger.merge_file(exec_file1, migrated_file1)
        merged2 = merger.merge_file(exec_file2, migrated_file2)
        
        # 合并后的文件保持独立
        assert 10 in merged1
        assert 11 in merged1
        assert 20 in merged2
        assert 20 not in merged1
    
    def test_max_instruction_counts(self):
        """测试指令计数取 max"""
        exec_lines = {
            10: LineCoverage(line_no=10, ci=5, mi=1, status="covered", sources=["unittest"]),
        }
        
        migrated_lines = {
            10: LineCoverage(line_no=10, ci=3, mi=2, status="covered", sources=["inherited"]),
        }
        
        merger = LedgerMerger()
        merged = merger.merge_file(exec_lines, migrated_lines)
        
        # ci 取 max, mi 取 min
        assert merged[10].ci == 5
        assert merged[10].mi == 1
