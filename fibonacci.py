def fibonacci(n):
    """
    Return the nth Fibonacci number.
    
    Fibonacci sequence: F(0) = 0, F(1) = 1, F(n) = F(n-1) + F(n-2) for n >= 2.
    
    Args:
        n: An integer. Can be positive, zero, or negative.
        
    Returns:
        The nth Fibonacci number.
        - For n >= 0: standard Fibonacci number.
        - For n < 0: extended Fibonacci (Neo-Fibonacci) where
          F(-n) = (-1)^(n+1) * F(n).
        
    Raises:
        ValueError: If n is not an integer.
    """
    if not isinstance(n, int):
        raise ValueError(f"Input must be an integer, got {type(n).__name__}")
    
    if n >= 0:
        # Standard Fibonacci
        if n == 0:
            return 0
        elif n == 1:
            return 1
        
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b
    else:
        # Negative n: use extended Fibonacci
        # F(-n) = (-1)^(n+1) * F(n)
        abs_n = -n
        fib_abs = fibonacci(abs_n)
        if abs_n % 2 == 0:
            return -fib_abs
        else:
            return fib_abs


def main():
    """Test the fibonacci function with various inputs."""
    test_cases = [
        (0, 0, "F(0) = 0"),
        (1, 1, "F(1) = 1"),
        (2, 1, "F(2) = 1"),
        (3, 2, "F(3) = 2"),
        (4, 3, "F(4) = 3"),
        (5, 5, "F(5) = 5"),
        (6, 8, "F(6) = 8"),
        (7, 13, "F(7) = 13"),
        (10, 55, "F(10) = 55"),
        (20, 6765, "F(20) = 6765"),
        (-1, 1, "F(-1) = 1"),
        (-2, -1, "F(-2) = -1"),
        (-3, 2, "F(-3) = 2"),
        (-4, -3, "F(-4) = -3"),
        (-5, 5, "F(-5) = 5"),
        (-6, -8, "F(-6) = -8"),
        (-7, 13, "F(-7) = 13"),
    ]
    
    all_passed = True
    for n, expected, desc in test_cases:
        try:
            result = fibonacci(n)
            status = "PASS" if result == expected else "FAIL"
            if status == "FAIL":
                all_passed = False
                print(f"{status}: {desc}, got {result}, expected {expected}")
            else:
                print(f"{status}: {desc}")
        except Exception as e:
            all_passed = False
            print(f"FAIL: {desc}, raised {type(e).__name__}: {e}")
    
    # Edge cases
    print("\n--- Edge case tests ---")
    
    # Large number (to check performance)
    try:
        result = fibonacci(100)
        expected = 354224848179261915075
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"{status}: F(100) = {result}")
    except Exception as e:
        all_passed = False
        print(f"FAIL: F(100), raised {type(e).__name__}: {e}")
    
    # Non-integer input
    try:
        fibonacci(3.5)
        all_passed = False
        print("FAIL: F(3.5) should raise ValueError")
    except ValueError as e:
        print(f"PASS: F(3.5) raises ValueError: {e}")
    except Exception as e:
        all_passed = False
        print(f"FAIL: F(3.5) raised unexpected {type(e).__name__}: {e}")
    
    # String input
    try:
        fibonacci("5")
        all_passed = False
        print("FAIL: F('5') should raise ValueError")
    except ValueError as e:
        print(f"PASS: F('5') raises ValueError: {e}")
    except Exception as e:
        all_passed = False
        print(f"FAIL: F('5') raised unexpected {type(e).__name__}: {e}")
    
    # Negative edge: largest negative
    try:
        result = fibonacci(-10)
        expected = -55  # F(-10) = -F(10) since 10 is even
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"{status}: F(-10) = {result}")
    except Exception as e:
        all_passed = False
        print(f"FAIL: F(-10), raised {type(e).__name__}: {e}")
    
    print(f"\n{'All tests passed!' if all_passed else 'Some tests failed!'}")


if __name__ == "__main__":
    main()
