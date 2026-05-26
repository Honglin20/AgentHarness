#!/usr/bin/env python3
"""
hello.py - 一个健壮的"Hello"打印程序
包含完整的错误处理和边界条件测试
"""

import sys
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def print_hello(name: str = "hello") -> str:
    """
    打印问候语，并返回结果字符串。
    
    如果输入（去除首尾空白后）是"hello"（不区分大小写），则原样打印；
    否则打印 "hello, {name}"。
    
    Args:
        name: 要打印的字符串，默认为"hello"
    
    Returns:
        返回打印的字符串
    
    Raises:
        TypeError: 如果输入不是字符串
        ValueError: 如果输入为空字符串或仅包含空白字符
    """
    # 类型检查
    if not isinstance(name, str):
        raise TypeError(f"输入必须是字符串，而不是 {type(name).__name__}")
    
    # 空值检查
    if not name.strip():
        raise ValueError("输入不能为空字符串或仅包含空白字符")
    
    # 判断逻辑：strip后比较（不区分大小写）
    stripped = name.strip()
    if stripped.lower() == "hello":
        message = name  # 原样输出
    else:
        message = f"hello, {name}"
    
    print(message)
    logger.info(f"成功打印: '{message}'")
    return message


def run_tests():
    """运行边界条件测试"""
    print("\n===== 开始测试 =====")
    
    # 正常测试用例 (输入, 期望输出)
    test_cases = [
        ("hello", "hello"),
        ("HELLO", "HELLO"),
        ("Hello", "Hello"),
        ("  hello  ", "  hello  "),       # 前后有空格，但strip后是hello
        ("\thello\n", "\thello\n"),       # 包含转义字符
        ("world", "hello, world"),
        ("Python", "hello, Python"),
        ("123", "hello, 123"),
        ("  world  ", "hello,   world  "),
    ]
    
    # 异常测试用例 (输入, 期望异常类型)
    error_cases = [
        (123, TypeError),
        (None, TypeError),
        (3.14, TypeError),
        ([], TypeError),
        ({}, TypeError),
        (True, TypeError),
        ("", ValueError),
        ("   ", ValueError),
        ("\n\t ", ValueError),
    ]
    
    all_passed = True
    
    # 正常测试
    print("\n--- 正常值测试 ---")
    for inp, expected in test_cases:
        try:
            result = print_hello(inp)
            assert result == expected, f"预期 '{expected}', 但得到 '{result}'"
            logger.info(f"✓ 通过: print_hello({inp!r}) => {result!r}")
        except AssertionError as e:
            logger.error(f"✗ 失败: {e}")
            all_passed = False
        except Exception as e:
            logger.error(f"✗ 异常: print_hello({inp!r}) 抛出 {type(e).__name__}: {e}")
            all_passed = False
    
    # 错误测试
    print("\n--- 异常值测试 ---")
    for inp, expected_exc in error_cases:
        try:
            print_hello(inp)
            logger.error(f"✗ 失败: print_hello({inp!r}) 应该抛出 {expected_exc.__name__}")
            all_passed = False
        except expected_exc as e:
            logger.info(f"✓ 通过: print_hello({inp!r}) 正确抛出 {type(e).__name__}: {e}")
        except Exception as e:
            logger.error(f"✗ 失败: print_hello({inp!r}) 预期 {expected_exc.__name__}, 但得到 {type(e).__name__}: {e}")
            all_passed = False
    
    print("\n===== 测试结束 =====")
    return all_passed


def main():
    """主函数"""
    print("=== 演示 ===")
    print("\n1. 默认调用:")
    print_hello()
    
    print("\n2. 带参数调用:")
    print_hello("world")
    
    print("\n3. 边界情况:")
    print_hello("  hello  ")  # 带空格的hello
    print_hello("HELLO")      # 大写
    
    # 运行测试
    print("\n" + "="*50)
    success = run_tests()
    
    print("\n" + "="*50)
    if success:
        print("✅ 所有测试通过!")
        return 0
    else:
        print("❌ 存在测试失败!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
