# 执行计划摘要

---

## 1. 任务概述

| 项目 | 内容 |
|------|------|
| **任务描述** | Review: `def div(a,b): return a/b` |
| **上游分析来源** | 代码分析专家（analyzer） |
| **任务目标** | 对除法函数 `div(a,b)` 进行评审，发现并修复潜在问题，输出改进后的代码 |

---

## 2. 上游分析结果确认

### 2.1 已发现的问题

| 编号 | 问题 | 严重程度 | 说明 |
|:----:|------|:--------:|------|
| P1 | **除零错误风险** | 🔴 严重 | 当 `b == 0` 时抛出 `ZeroDivisionError`，无防护处理 |
| P2 | **类型不明确** | 🟡 中等 | 缺少类型提示，参数可为任意类型，非数字传入会抛出 `TypeError` |
| P3 | **Python 2/3 除法差异** | 🟢 轻微 | Python 2 整数除法截断（`5/2=2`），Python 3 返回 float（`5/2=2.5`） |
| P4 | **缺少函数文档** | 🟢 轻微 | 无 docstring 说明功能、参数和返回值 |

### 2.2 改进建议（来自上游分析）

```python
from __future__ import division  # 确保 Python 2 也返回 float

def div(a: float, b: float) -> float:
    """返回 a 除以 b 的结果。
    
    Args:
        a: 被除数
        b: 除数（不能为 0）
        
    Returns:
        商
        
    Raises:
        ZeroDivisionError: 当 b 为 0 时
    """
    if b == 0:
        raise ZeroDivisionError("除数不能为零")
    return a / b
```

---

## 3. 执行步骤

| 步骤 | 操作 | 详细说明 | 预期输出 | 状态 |
|:----:|------|----------|----------|:----:|
| 1 | **生成改进代码** | 基于上游分析建议，编写包含防护、类型提示、文档的完整代码 | `fixed_code.py` 文件 | ⏳ 待执行 |
| 2 | **代码风格审查** | 检查是否遵循 PEP 8 规范（命名、空格、缩进等） | 审查通过/修改建议 | ⏳ 待执行 |
| 3 | **功能正确性验证** | 使用 `runner` 执行测试用例，验证各种场景下函数行为正确 | 测试通过 | ⏳ 待执行 |
| 4 | **边界条件测试** | 测试 `b=0` 抛出 `ZeroDivisionError`、传入非数字类型抛出 `TypeError` | 异常处理正确 | ⏳ 待执行 |
| 5 | **输出最终评审结论** | 汇总所有发现、修复和验证结果 | 完整的评审报告 | ⏳ 待执行 |

---

## 4. 详细执行指令

### 步骤 1：生成改进代码

将以下代码写入 `fixed_code.py`：

```python
from __future__ import division


def div(a: float, b: float) -> float:
    """返回 a 除以 b 的结果。

    Args:
        a: 被除数
        b: 除数（不能为 0）

    Returns:
        商

    Raises:
        ZeroDivisionError: 当 b 为 0 时
        TypeError: 当 a 或 b 不是数字类型时
    """
    if not isinstance(a, (int, float)):
        raise TypeError(f"被除数 a 必须为数字类型，实际为 {type(a).__name__}")
    if not isinstance(b, (int, float)):
        raise TypeError(f"除数 b 必须为数字类型，实际为 {type(b).__name__}")
    if b == 0:
        raise ZeroDivisionError("除数不能为零")
    return a / b
```

### 步骤 2：代码风格审查要点

| 审查项 | 检查内容 |
|--------|----------|
| 命名规范 | 函数名 `div` 是否合理？是否为动词/动名词？ |
| 空行规范 | 顶级函数前后空 2 行（PEP 8） |
| 导入规范 | `from __future__ import division` 位于文件顶部 |
| 注释规范 | docstring 格式是否符合 Google/NumPy 风格 |
| 类型提示 | `a: float, b: float` 和 `-> float` 是否准确 |

### 步骤 3：功能正确性验证（使用 runner 执行）

用 bash 执行以下测试脚本：

```python
# test_div.py
from fixed_code import div

# 正常测试
assert div(10, 2) == 5.0, "正常除法失败"
assert div(5, 2) == 2.5, "浮点除法失败"
assert div(0, 5) == 0.0, "零除以正数失败"
assert div(-6, 3) == -2.0, "负数除法失败"

# 边界测试
try:
    div(5, 0)
    assert False, "应抛出异常但未抛出"
except ZeroDivisionError as e:
    assert str(e) == "除数不能为零", f"异常消息错误: {e}"

try:
    div("a", 2)
    assert False, "应抛出异常但未抛出"
except TypeError:
    pass

print("✅ 所有测试通过！")
```

### 步骤 4：边界条件测试

| 测试用例 | 输入 | 预期行为 | 验证方式 |
|----------|------|----------|----------|
| 正常除法 | `div(10, 2)` | 返回 `5.0` | assert 相等 |
| 整数除法（Python 3 行为） | `div(5, 2)` | 返回 `2.5`（非截断） | assert 相等 |
| 零除以正数 | `div(0, 5)` | 返回 `0.0` | assert 相等 |
| 负数除法 | `div(-6, 3)` | 返回 `-2.0` | assert 相等 |
| 除零错误 | `div(5, 0)` | 抛出 `ZeroDivisionError` | try/except |
| 非数字类型 a | `div("a", 2)` | 抛出 `TypeError` | try/except |
| 非数字类型 b | `div(5, "b")` | 抛出 `TypeError` | try/except |

### 步骤 5：输出最终评审结论

评审结论应包含：
1. **原始代码问题回顾**（P1-P4）
2. **已实施的改进**（类型提示、异常处理、文档、导入）
3. **测试验证结果**（通过率）
4. **最终代码**（改进后的完整代码）
5. **遗留风险**（如有）

---

## 5. 验证标准

| 编号 | 验证项 | 预期 | 检查方式 |
|:----:|--------|------|----------|
| V1 | 代码文件存在 | `fixed_code.py` 已生成 | 检查文件是否存在 |
| V2 | 除零保护 | `b == 0` 时抛出 `ZeroDivisionError` | 运行测试用例 |
| V3 | 类型提示 | 参数和返回值有类型标注 | 检查代码 |
| V4 | 文档字符串 | 包含功能、参数、返回值、异常说明 | 检查代码 |
| V5 | 类型检查 | 非数字类型传入抛出 `TypeError` | 运行测试用例 |
| V6 | 导入语句 | 文件顶部有 `from __future__ import division` | 检查代码 |
| V7 | 所有测试通过 | 测试脚本执行无 assert 失败 | 运行测试脚本 |
| V8 | PEP 8 合规 | 符合 Python 代码风格规范 | 代码审查 |

---

## 6. 风险与预案

| 风险 | 影响 | 预案 |
|------|------|------|
| `from __future__ import division` 在 Python 3 中无实际效果 | 无负面影响，但 Python 2 用户可受益 | 保留该导入，兼容 Python 2/3 |
| 类型检查 `isinstance` 可能拒绝 `numpy.float64` 等类型 | 科学计算场景受限 | 可放宽为鸭子类型 + 仅在 `TypeError` 发生时提示 |
| 函数名 `div` 不够直观 | 可读性一般 | 可考虑重命名为 `safe_divide` 或 `divide`，但保持与原始代码一致 |
| 过度防护可能改变原始 API 行为 | 原始代码无防护，新代码增加了约束 | 符合防御式编程原则，属改进 |

---

## 7. 结论

| 维度 | 评价 |
|------|------|
| **上游分析质量** | ✅ 全面识别了 4 个问题，覆盖除零、类型、兼容性、文档 |
| **改进方案可行性** | ✅ 改进代码可直接用于替换原始代码 |
| **测试覆盖度** | ✅ 覆盖正常路径、边界条件、异常路径 |
| **风险控制** | ✅ 已识别潜在风险并制定预案 |

**核心改进要点**：
1. ✅ **除零保护** — 添加 `b == 0` 检查，抛出明确的 `ZeroDivisionError`
2. ✅ **类型防护** — 添加 `isinstance` 检查和 `TypeError` 异常
3. ✅ **类型提示** — 添加 `a: float, b: float -> float` 类型标注
4. ✅ **文档完善** — 添加完整的 docstring（功能、参数、返回值、异常）
5. ✅ **兼容性** — 添加 `from __future__ import division` 确保 Python 2/3 行为一致
