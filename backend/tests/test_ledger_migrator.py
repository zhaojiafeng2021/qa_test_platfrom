"""测试账本迁移器"""

import pytest
from app.modules.coverage_java.java_method_parser import MethodUnit
from app.modules.coverage_java.ledger_migrator import LedgerMigrator, LineCoverage, MigrationStats


class TestLedgerMigrator:
    """账本迁移器测试"""
    
    def test_design_example_add_div(self):
        """测试设计文档 4.4 节示例：add 保留，div 清零"""
        # v1: add(10-12), div(14-16)
        old_units = [
            MethodUnit(key="Calc#add(int,int)", fingerprint="fp_add_v1", start=10, end=12),
            MethodUnit(key="Calc#div(int,int)", fingerprint="fp_div_v1", start=14, end=16),
        ]
        
        # v2: 新增注释（方法外），add(11-13), div(15-18，修复后）
        new_units = [
            MethodUnit(key="Calc#add(int,int)", fingerprint="fp_add_v1", start=11, end=13),  # 指纹相同
            MethodUnit(key="Calc#div(int,int)", fingerprint="fp_div_v2", start=15, end=18),  # 指纹不同
        ]
        
        # v1 覆盖：add 全覆盖，div 第 14 行未覆盖
        old_coverage = {
            10: LineCoverage(line_no=10, ci=2, status="covered", sources=["unittest"]),
            11: LineCoverage(line_no=11, ci=3, status="covered", sources=["runtime"]),
            12: LineCoverage(line_no=12, ci=1, status="covered", sources=["unittest"]),
            14: LineCoverage(line_no=14, ci=0, mi=2, status="missed", sources=[]),
            15: LineCoverage(line_no=15, ci=3, status="covered", sources=["runtime"]),
            16: LineCoverage(line_no=16, ci=1, status="covered", sources=["runtime"]),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # add 偏移 +1：10→11, 11→12, 12→13，sources 变 inherited
        assert 11 in migrated
        assert migrated[11].ci == 2
        assert migrated[11].status == "covered"
        assert migrated[11].sources == ["inherited"]
        
        assert 12 in migrated
        assert migrated[12].ci == 3
        assert migrated[12].sources == ["inherited"]
        
        assert 13 in migrated
        assert migrated[13].ci == 1
        
        # div 清零：15-18 全部 missed
        assert 15 in migrated
        assert migrated[15].status == "missed"
        assert migrated[15].sources == []
        
        assert 16 in migrated
        assert migrated[16].status == "missed"
        
        assert 17 in migrated
        assert 18 in migrated
        
        # 统计
        assert stats.methods_kept == 1
        assert stats.methods_reset == 1
        assert stats.methods_removed == 0
        assert stats.methods_added == 0
        assert "Calc#div(int,int)" in stats.reset_methods
    
    def test_method_removed(self):
        """测试方法删除"""
        old_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="A#method2()", fingerprint="fp2", start=14, end=16),
        ]
        
        new_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
            14: LineCoverage(line_no=14, ci=1, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # method1 保留
        assert 10 in migrated
        
        # method2 被删除，不出现在迁移结果中
        assert 14 not in migrated
        
        assert stats.methods_kept == 1
        assert stats.methods_removed == 1
    
    def test_method_added(self):
        """测试方法新增"""
        old_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
        ]
        
        new_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="A#method2()", fingerprint="fp2", start=14, end=16),
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # method1 保留
        assert 10 in migrated
        
        # method2 新增，全部 missed
        assert 14 in migrated
        assert migrated[14].status == "missed"
        assert 15 in migrated
        assert 16 in migrated
        
        assert stats.methods_kept == 1
        assert stats.methods_added == 1
    
    def test_method_renamed(self):
        """测试方法重命名（视为删除 + 新增）"""
        old_units = [
            MethodUnit(key="A#oldName()", fingerprint="fp1", start=10, end=12),
        ]
        
        new_units = [
            MethodUnit(key="A#newName()", fingerprint="fp1", start=10, end=12),  # 指纹相同但 key 不同
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 旧方法删除，新方法当作新增
        assert stats.methods_removed == 1
        assert stats.methods_added == 1
        assert stats.methods_kept == 0
        
        # newName 全部 missed
        assert migrated[10].status == "missed"
    
    def test_offset_calculation(self):
        """测试行号偏移计算"""
        old_units = [
            MethodUnit(key="A#method()", fingerprint="fp1", start=10, end=12),
        ]
        
        new_units = [
            MethodUnit(key="A#method()", fingerprint="fp1", start=15, end=17),  # 偏移 +5
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
            11: LineCoverage(line_no=11, ci=2, status="covered"),
            12: LineCoverage(line_no=12, ci=3, status="partial", cb=1, mb=1),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 10→15, 11→16, 12→17
        assert 15 in migrated
        assert migrated[15].ci == 1
        
        assert 16 in migrated
        assert migrated[16].ci == 2
        
        assert 17 in migrated
        assert migrated[17].status == "partial"
        assert migrated[17].cb == 1
        assert migrated[17].mb == 1
    
    def test_field_init_migration(self):
        """测试字段初始化迁移（伪单元）"""
        old_units = [
            MethodUnit(key="A#<init-fields>", fingerprint="fp1", lines=[5, 6]),
        ]
        
        new_units = [
            MethodUnit(key="A#<init-fields>", fingerprint="fp1", lines=[10, 11]),  # 新增行后移动
        ]
        
        old_coverage = {
            5: LineCoverage(line_no=5, ci=1, status="covered"),
            6: LineCoverage(line_no=6, ci=2, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 按索引对应：5→10, 6→11
        assert 10 in migrated
        assert migrated[10].ci == 1
        
        assert 11 in migrated
        assert migrated[11].ci == 2
        
        assert stats.methods_kept == 1
    
    def test_field_init_lines_changed(self):
        """测试字段初始化行数改变（指纹不同，清零）"""
        old_units = [
            MethodUnit(key="A#<init-fields>", fingerprint="fp1", lines=[5, 6]),
        ]
        
        new_units = [
            MethodUnit(key="A#<init-fields>", fingerprint="fp2", lines=[5, 6, 7]),  # 新增字段
        ]
        
        old_coverage = {
            5: LineCoverage(line_no=5, ci=1, status="covered"),
            6: LineCoverage(line_no=6, ci=2, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 指纹不同，清零
        assert 5 in migrated
        assert migrated[5].status == "missed"
        assert 6 in migrated
        assert 7 in migrated
        
        assert stats.methods_reset == 1
    
    def test_exclude_classes(self):
        """测试排除 JaCoCo 不一致的类"""
        old_units = [
            MethodUnit(key="com.example.Good#method()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="com.example.Bad#method()", fingerprint="fp2", start=20, end=22),
        ]
        
        new_units = [
            MethodUnit(key="com.example.Good#method()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="com.example.Bad#method()", fingerprint="fp2", start=20, end=22),
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
            20: LineCoverage(line_no=20, ci=2, status="covered"),
        }
        
        exclude_classes = {"com.example.Bad"}
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage, exclude_classes)
        
        # Good 保留
        assert 10 in migrated
        assert migrated[10].sources == ["inherited"]
        
        # Bad 被排除，不出现在迁移结果中
        assert 20 not in migrated
        
        # Bad 不计入统计
        assert stats.methods_kept == 1
    
    def test_exclude_inner_class(self):
        """测试排除包含内部类（$ 分隔）"""
        old_units = [
            MethodUnit(key="com.example.Outer$Inner#method()", fingerprint="fp1", start=10, end=12),
        ]
        
        new_units = [
            MethodUnit(key="com.example.Outer$Inner#method()", fingerprint="fp1", start=10, end=12),
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
        }
        
        # 排除外部类会同时排除内部类
        exclude_classes = {"com.example.Outer"}
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage, exclude_classes)
        
        # 内部类被排除
        assert 10 not in migrated
    
    def test_file_deleted(self):
        """测试文件删除（所有方法删除）"""
        old_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="A#method2()", fingerprint="fp2", start=14, end=16),
        ]
        
        new_units = []  # 文件删除
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=1, status="covered"),
            14: LineCoverage(line_no=14, ci=1, status="covered"),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 所有行都不出现
        assert len(migrated) == 0
        
        assert stats.methods_removed == 2
    
    def test_file_added(self):
        """测试文件新增（所有方法新增）"""
        old_units = []
        
        new_units = [
            MethodUnit(key="A#method1()", fingerprint="fp1", start=10, end=12),
            MethodUnit(key="A#method2()", fingerprint="fp2", start=14, end=16),
        ]
        
        old_coverage = {}
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # 所有行都是 missed
        assert 10 in migrated
        assert migrated[10].status == "missed"
        assert 14 in migrated
        
        assert stats.methods_added == 2
    
    def test_partial_coverage_migrated(self):
        """测试部分覆盖的迁移"""
        old_units = [
            MethodUnit(key="A#method()", fingerprint="fp1", start=10, end=12),
        ]
        
        new_units = [
            MethodUnit(key="A#method()", fingerprint="fp1", start=10, end=12),
        ]
        
        old_coverage = {
            10: LineCoverage(line_no=10, ci=2, mi=1, cb=1, mb=1, status="partial", sources=["unittest"]),
        }
        
        migrator = LedgerMigrator()
        migrated, stats = migrator.migrate(old_units, new_units, old_coverage)
        
        # partial 状态和分支数保留
        assert migrated[10].status == "partial"
        assert migrated[10].ci == 2
        assert migrated[10].mi == 1
        assert migrated[10].cb == 1
        assert migrated[10].mb == 1
        assert migrated[10].sources == ["inherited"]
