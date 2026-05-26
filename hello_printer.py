#!/usr/bin/env python3
"""
A robust hello printer module with error handling and tests.
"""

import sys
import io

def print_hello(target="World", output_stream=None):
    """
    Prints a greeting message.
    
    Args:
        target (str): The name to greet. Defaults to "World".
        output_stream: The output stream to write to. Defaults to sys.stdout.
    
    Returns:
        str: The greeting string that was printed.
    
    Raises:
        TypeError: If target is not a string.
        ValueError: If target is empty or contains only whitespace.
    """
    # Type checking
    if not isinstance(target, str):
        raise TypeError(f"target must be a string, got {type(target).__name__}")
    
    # Value validation - boundary condition
    if not target.strip():
        raise ValueError("target must be a non-empty string")
    
    greeting = f"Hello, {target}!"
    
    # Determine output stream
    out = output_stream if output_stream is not None else sys.stdout
    
    try:
        print(greeting, file=out)
    except Exception as e:
        raise IOError(f"Failed to write to output stream: {e}")
    
    return greeting


def test_print_hello():
    """Test suite for print_hello function."""
    print("=" * 50)
    print("Running tests for print_hello...")
    print("=" * 50)
    
    passed = 0
    failed = 0
    
    # Test 1: Normal case - default target
    try:
        result = print_hello()
        assert result == "Hello, World!", f"Expected 'Hello, World!', got '{result}'"
        print("[PASS] Test 1: Default target 'World'")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 1: Default target 'World' - {e}")
        failed += 1
    
    # Test 2: Normal case - custom target
    try:
        result = print_hello("Alice")
        assert result == "Hello, Alice!", f"Expected 'Hello, Alice!', got '{result}'"
        print("[PASS] Test 2: Custom target 'Alice'")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 2: Custom target 'Alice' - {e}")
        failed += 1
    
    # Test 3: Empty string (boundary)
    try:
        print_hello("")
        print("[FAIL] Test 3: Empty string should raise ValueError")
        failed += 1
    except ValueError:
        print("[PASS] Test 3: Empty string raises ValueError")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 3: Empty string - unexpected exception {type(e).__name__}: {e}")
        failed += 1
    
    # Test 4: Whitespace-only string (boundary)
    try:
        print_hello("   ")
        print("[FAIL] Test 4: Whitespace-only string should raise ValueError")
        failed += 1
    except ValueError:
        print("[PASS] Test 4: Whitespace-only string raises ValueError")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 4: Whitespace-only string - unexpected exception {type(e).__name__}: {e}")
        failed += 1
    
    # Test 5: Non-string input (type error)
    try:
        print_hello(123)
        print("[FAIL] Test 5: Non-string input should raise TypeError")
        failed += 1
    except TypeError:
        print("[PASS] Test 5: Non-string input raises TypeError")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 5: Non-string input - unexpected exception {type(e).__name__}: {e}")
        failed += 1
    
    # Test 6: None input (type error)
    try:
        print_hello(None)
        print("[FAIL] Test 6: None input should raise TypeError")
        failed += 1
    except TypeError:
        print("[PASS] Test 6: None input raises TypeError")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 6: None input - unexpected exception {type(e).__name__}: {e}")
        failed += 1
    
    # Test 7: Custom output stream (StringIO)
    try:
        string_buffer = io.StringIO()
        result = print_hello("Bob", output_stream=string_buffer)
        assert result == "Hello, Bob!", f"Expected 'Hello, Bob!', got '{result}'"
        output_content = string_buffer.getvalue().strip()
        assert output_content == "Hello, Bob!", f"Stream content mismatch: '{output_content}'"
        print("[PASS] Test 7: Custom output stream (StringIO)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 7: Custom output stream - {e}")
        failed += 1
    
    # Test 8: Special characters in target
    try:
        result = print_hello("John Doe!")
        assert result == "Hello, John Doe!!", f"Expected 'Hello, John Doe!!', got '{result}'"
        print("[PASS] Test 8: Special characters in target")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 8: Special characters in target - {e}")
        failed += 1
    
    # Test 9: Very long target string (boundary)
    try:
        long_name = "A" * 10000
        result = print_hello(long_name)
        assert result == f"Hello, {long_name}!", f"Long string test failed"
        print("[PASS] Test 9: Very long target string (10000 chars)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 9: Very long target string - {e}")
        failed += 1
    
    # Test 10: Unicode characters
    try:
        result = print_hello("世界")
        assert result == "Hello, 世界!", f"Unicode test failed: '{result}'"
        print("[PASS] Test 10: Unicode characters (世界)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 10: Unicode characters - {e}")
        failed += 1
    
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 50)
    
    return failed == 0


def interactive_mode():
    """Interactive mode that prompts user for input."""
    print("Hello Printer - Interactive Mode")
    print("Enter a name to greet (or 'quit' to exit):")
    
    while True:
        try:
            user_input = input("Name: ").strip()
            if user_input.lower() == 'quit':
                print("Goodbye!")
                break
            if not user_input:
                print("Please enter a non-empty name.")
                continue
            print_hello(user_input)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    # Run tests
    success = test_print_hello()
    
    print("\n")
    
    # Demonstrate basic usage
    print("Demonstration:")
    print_hello()
    print_hello("GitHub Copilot")
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)
