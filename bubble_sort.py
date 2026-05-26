def bubble_sort(arr):
    """
    冒泡排序算法
    对列表进行原地排序（升序）
    """
    n = len(arr)
    # 遍历所有元素
    for i in range(n):
        # 标志位，用于优化：如果某轮没有交换，说明已排序完成
        swapped = False
        # 最后 i 个元素已经排好，无需再比较
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                # 交换相邻元素
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        # 如果本轮没有交换，提前结束
        if not swapped:
            break
    return arr


if __name__ == "__main__":
    # 测试用例
    test_arr = [64, 34, 25, 12, 22, 11, 90]
    print(f"排序前: {test_arr}")
    sorted_arr = bubble_sort(test_arr)
    print(f"排序后: {sorted_arr}")

    # 更多测试
    test_cases = [
        [],
        [1],
        [5, 4, 3, 2, 1],
        [1, 2, 3, 4, 5],
        [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5],
    ]
    for case in test_cases:
        original = case.copy()
        result = bubble_sort(case)
        print(f"{original} -> {result}")
