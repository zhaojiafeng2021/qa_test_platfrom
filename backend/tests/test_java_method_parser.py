"""测试 Java 方法解析器"""

import pytest
from app.modules.coverage_java.java_method_parser import JavaMethodParser, MethodUnit


class TestJavaMethodParser:
    """Java 方法解析器测试"""
    
    def test_simple_methods(self):
        """测试普通方法"""
        source = '''package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }
    
    public int sub(int a, int b) {
        return a - b;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Calculator.java")
        
        assert units is not None
        assert len(units) == 2
        
        add_unit = next(u for u in units if "add" in u.key)
        assert add_unit.key == "com.example.Calculator#add(int,int)"
        assert add_unit.start == 4
        assert add_unit.end == 6
        assert len(add_unit.fingerprint) == 40  # SHA-1
        
        sub_unit = next(u for u in units if "sub" in u.key)
        assert sub_unit.key == "com.example.Calculator#sub(int,int)"
    
    def test_method_overloading(self):
        """测试方法重载"""
        source = '''package com.example;

public class Math {
    public int add(int a, int b) {
        return a + b;
    }
    
    public double add(double a, double b) {
        return a + b;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Math.java")
        
        assert units is not None
        keys = [u.key for u in units]
        assert "com.example.Math#add(int,int)" in keys
        assert "com.example.Math#add(double,double)" in keys
    
    def test_constructor(self):
        """测试构造器"""
        source = '''package com.example;

public class Person {
    private String name;
    
    public Person(String name) {
        this.name = name;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Person.java")
        
        assert units is not None
        ctor = next((u for u in units if "<init>" in u.key), None)
        assert ctor is not None
        assert ctor.key == "com.example.Person#<init>(String)"
        assert ctor.start == 6
        assert ctor.end == 8
    
    def test_field_initialization(self):
        """测试字段初始化"""
        source = '''package com.example;

public class Config {
    private int port = 8080;
    private String host = "localhost";
    private boolean enabled;
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Config.java")
        
        assert units is not None
        init_unit = next((u for u in units if "<init-fields>" in u.key), None)
        assert init_unit is not None
        assert init_unit.key == "com.example.Config#<init-fields>"
        assert init_unit.lines == [4, 5]
        assert init_unit.start is None
        assert init_unit.end is None
    
    def test_static_block(self):
        """测试静态块"""
        source = '''package com.example;

public class Registry {
    static {
        System.out.println("init");
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Registry.java")
        
        assert units is not None
        clinit = next((u for u in units if "<clinit>" in u.key), None)
        assert clinit is not None
        assert clinit.key == "com.example.Registry#<clinit>"
        assert clinit.start == 4
        assert clinit.end == 6
    
    def test_inner_class(self):
        """测试内部类"""
        source = '''package com.example;

public class Outer {
    public void outerMethod() {
        return;
    }
    
    public class Inner {
        public void innerMethod() {
            return;
        }
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Outer.java")
        
        assert units is not None
        keys = [u.key for u in units]
        assert "com.example.Outer#outerMethod()" in keys
        assert "com.example.Outer.Inner#innerMethod()" in keys
    
    def test_skip_strings_and_comments(self):
        """测试跳过字符串和注释中的花括号"""
        source = '''package com.example;

public class Tricky {
    public void method() {
        String s = "{ not a brace }";
        // } this is comment
        /* } also comment */
        char c = '}';
        return;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Tricky.java")
        
        assert units is not None
        method = next(u for u in units if "method" in u.key)
        assert method.end == 10  # 正确找到实际的结束行
    
    def test_text_block_java13plus(self):
        """测试文本块（Java 13+）"""
        source = '''package com.example;

public class Modern {
    public void method() {
        String json = """
            {
                "key": "value"
            }
            """;
        return;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Modern.java")
        
        assert units is not None
        method = next(u for u in units if "method" in u.key)
        assert method.end == 11
    
    def test_fingerprint_same_for_identical_code(self):
        """测试相同代码的指纹相同"""
        source1 = '''package com.example;
public class A {
    public int add(int a, int b) {
        return a + b;
    }
}'''
        source2 = '''package com.other;
public class B {
    public int add(int a, int b) {
        return a + b;
    }
}'''
        parser = JavaMethodParser()
        units1 = parser.parse_file(source1, "com/example/A.java")
        units2 = parser.parse_file(source2, "com/other/B.java")
        
        assert units1[0].fingerprint == units2[0].fingerprint
    
    def test_fingerprint_different_for_modified_code(self):
        """测试修改代码后指纹不同"""
        source1 = '''package com.example;
public class A {
    public int div(int a, int b) {
        return a / b;
    }
}'''
        source2 = '''package com.example;
public class A {
    public int div(int a, int b) {
        if (b == 0) throw new RuntimeException();
        return a / b;
    }
}'''
        parser = JavaMethodParser()
        units1 = parser.parse_file(source1, "com/example/A.java")
        units2 = parser.parse_file(source2, "com/example/A.java")
        
        assert units1[0].fingerprint != units2[0].fingerprint
    
    def test_fingerprint_same_for_comment_outside_method(self):
        """测试方法外注释改动不影响指纹"""
        source1 = '''package com.example;
// comment v1
public class A {
    public int add(int a, int b) {
        return a + b;
    }
}'''
        source2 = '''package com.example;
// comment v2 changed
public class A {
    public int add(int a, int b) {
        return a + b;
    }
}'''
        parser = JavaMethodParser()
        units1 = parser.parse_file(source1, "com/example/A.java")
        units2 = parser.parse_file(source2, "com/example/A.java")
        
        # 方法外注释不影响方法指纹
        assert units1[0].fingerprint == units2[0].fingerprint
    
    def test_fingerprint_different_for_comment_inside_method(self):
        """测试方法内注释改动影响指纹（决策 1）"""
        source1 = '''package com.example;
public class A {
    public int add(int a, int b) {
        // old comment
        return a + b;
    }
}'''
        source2 = '''package com.example;
public class A {
    public int add(int a, int b) {
        // new comment
        return a + b;
    }
}'''
        parser = JavaMethodParser()
        units1 = parser.parse_file(source1, "com/example/A.java")
        units2 = parser.parse_file(source2, "com/example/A.java")
        
        # 方法内注释改动导致指纹不同
        assert units1[0].fingerprint != units2[0].fingerprint
    
    def test_annotation_with_braces(self):
        """测试注解中的花括号"""
        source = '''package com.example;

public class Annotated {
    @SomeAnnotation(value = {1, 2, 3})
    public void method() {
        return;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Annotated.java")
        
        assert units is not None
        method = next(u for u in units if "method" in u.key)
        assert method.start == 5
        assert method.end == 7
    
    def test_no_overlap_validation(self):
        """测试方法范围不交叉验证"""
        source = '''package com.example;
public class Good {
    public void method1() {
        return;
    }
    
    public void method2() {
        return;
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Good.java")
        
        assert units is not None
        assert parser._validate_no_overlap(units) is True
    
    def test_parse_failure_returns_none(self):
        """测试解析失败返回 None"""
        invalid_source = '''this is not valid java code {{{'''
        parser = JavaMethodParser()
        units = parser.parse_file(invalid_source, "com/example/Invalid.java")
        
        assert units is None
    
    def test_generic_method(self):
        """测试泛型方法"""
        source = '''package com.example;
import java.util.List;

public class Generic {
    public <T> T first(List<T> list) {
        return list.get(0);
    }
}'''
        parser = JavaMethodParser()
        units = parser.parse_file(source, "com/example/Generic.java")
        
        assert units is not None
        method = next(u for u in units if "first" in u.key)
        # 泛型参数类型包含 <>
        assert "List" in method.key
