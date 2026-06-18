# Phase 1: outline 走 iter_index

> **目标**：D1 决策落地。outline 不再扫 events buffer 算 iter_count，直接读 iter_index。
> **ADR 依据**：D1
> **预估**：0.5 天，8 个任务
> **用户感知**：iter dropdown 终于能显示多个 iter。

## 任务清单

---

### P1-T01: `compute_outline` 签名加 `iter_index` 参数

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P0 完成
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
为 outline_compute.py 增加 iter_index 输入参数，作为后续替代 events 扫描的准备工作。本任务只改签名 + docstring，不改实现。

#### 代码计划
- **`harness/persistence/outline_compute.py`** (修改)
  - `compute_outline(...)` 签名加 `iter_index: dict[str, list[dict]] | None = None`
  - docstring 说明：iter_index 是 iter 元数据的权威来源，未来 events 扫描会被移除
  - 函数体暂不使用 iter_index（P1-T02 才用）

#### 产出标准
- [ ] 函数签名含 iter_index 参数
- [ ] 默认 None 保持向后兼容
- [ ] 现有所有 caller 仍可工作（不传 iter_index）

#### 验证方法
```bash
python3 -c "
import inspect
from harness.persistence.outline_compute import compute_outline
sig = inspect.signature(compute_outline)
print('iter_index' in sig.parameters)
"
# 预期：True

python3 -m pytest harness/persistence/test_outline_compute.py -v 2>&1 | tail -5
# 预期：现有测试全过（向后兼容）
```

#### 代码质量检查
- [ ] 单一职责：本任务只改签名
- [ ] 开闭原则：默认 None 让旧 caller 不破坏
- [ ] 命名达意：`iter_index` 名字和 ADR 一致

#### Review 检查
- [ ] DoD 满足
- [ ] 现有测试无回归

---

### P1-T02: 移除 events-based `iter_set` 计算

**Phase**: P1
**预估**: ~15 分钟
**依赖**: P1-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
outline_compute.py 中第 73-94 行扫 events buffer 算 iter_set 的逻辑被替换为：从 iter_index 读取 (node, iter) 列表。

#### 代码计划
- **`harness/persistence/outline_compute.py`** (修改)
  - 删除 line 71-94 的 `iter_set` 从 events 推导的逻辑
  - 替换为：
    ```python
    iter_set = {}
    for node_id, entries in (iter_index or {}).items():
        for entry in entries:
            iter_num = entry.get('iter', 1)
            key = f"{node_id}__iter{iter_num}"
            iter_set[key] = {
                "node_id": node_id,
                "iteration": iter_num,
                "first_ts": entry.get("started_at") or float("inf"),
            }
    ```
  - 保留 line 96-110 的 conversation-based first_ts 细化（仍可优化 timestamp 精度）
  - 保留 line 112-121 的 idle node 合成（fallback）

#### 产出标准
- [ ] outline 不再依赖 events buffer 推导 iter_set
- [ ] outline 输出和 P1-T01 之前对真实 run 一致或更准确（iter_count 正确）
- [ ] 代码删除干净（无残留 events scan）

#### 验证方法
```bash
python3 -c "
import json
from harness.persistence.outline_compute import compute_outline

iter_index = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669+iter_index.json'))
conv = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669.json'))['conversation']
dag = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669.json'))['dag']

items = compute_outline(conversation=conv, events=None, trace=[], todo_steps={}, agents_snapshot=[], dag=dag, iter_index=iter_index)
from collections import Counter
print('scout iter count:', sum(1 for it in items if it['node_id']=='scout'))
print('selector iter count:', sum(1 for it in items if it['node_id']=='selector'))
"
# 预期：scout: 3, selector: 6（之前是 1）
```

#### 代码质量检查
- [ ] 单一职责：iter 来源唯一化
- [ ] Fail loud：iter_index 是 None 时不崩（fallback 处理在 P1-T03）
- [ ] 无残留：删干净 events scan 代码

#### Review 检查
- [ ] DoD 满足
- [ ] 真实 run 的 iter_count 数字正确（关键验证）

---

### P1-T03: 加 fallback：无 iter_index 时合成 iter=1

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P1-T02
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
旧 run 可能没 iter_index 文件，或 iter_index 不完整。outline 应 graceful degrade：fallback 给每个 dag node 合成 iter=1 条目。

#### 代码计划
- **`harness/persistence/outline_compute.py`** (修改)
  - 在 P1-T02 替换逻辑后加：
    ```python
    # Fallback: 无 iter_index 时为每个 dag node 合成 iter=1
    if not iter_index:
        for node_id in dag_nodes:
            key = f"{node_id}__iter1"
            iter_set.setdefault(key, {
                "node_id": node_id,
                "iteration": 1,
                "first_ts": msg_first_ts_by_node.get(node_id) or float("inf"),
            })
    ```

#### 产出标准
- [ ] iter_index=None 或 {} 时，每个 dag node 都有 iter=1 outline 条目
- [ ] 不抛异常

#### 验证方法
```bash
python3 -c "
from harness.persistence.outline_compute import compute_outline
items = compute_outline(conversation=[], events=None, trace=[], todo_steps={}, agents_snapshot=[], dag={'nodes': ['scout','selector']}, iter_index=None)
print('items count:', len(items))
print('nodes:', [it['node_id'] for it in items])
"
# 预期：items count: 2, nodes: ['scout', 'selector']
```

#### 代码质量检查
- [ ] 边界 case 处理：None / {} / 缺 node 都不崩
- [ ] Fail loud：dag_nodes 为空时不抛（返回空 list）

#### Review 检查
- [ ] DoD 满足
- [ ] fallback 行为符合预期

---

### P1-T04: `save_outline_sidecar` 传入 iter_index

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P1-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
outline_save 的入口函数加 iter_index 参数，透传给 compute_outline。

#### 代码计划
- **`harness/persistence/outline_save.py`** (修改)
  - `save_outline_sidecar(...)` 签名加 `iter_index: dict | None = None`
  - 透传给 `compute_outline(iter_index=iter_index, ...)`

#### 产出标准
- [ ] 函数签名含 iter_index
- [ ] docstring 说明数据来源（来自 RunStore.get_iter_index）

#### 验证方法
```bash
python3 -c "
import inspect
from harness.persistence.outline_save import save_outline_sidecar
print('iter_index' in inspect.signature(save_outline_sidecar).parameters)
"
# 预期：True
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 默认 None 向后兼容

#### Review 检查
- [ ] DoD 满足

---

### P1-T05: `_save_incremental` 把 iter_index 传给 outline_save

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P1-T04
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
incremental_save.py 已经读了 iter_index（line 63），把它也传给 save_outline_sidecar。

#### 代码计划
- **`harness/engine/incremental_save.py`** (修改)
  - line 249-257 的 `save_outline_sidecar(...)` 调用加 `iter_index=invocation_counts_raw`（line 63 已有的变量）

#### 产出标准
- [ ] save_outline_sidecar 调用传入 iter_index
- [ ] 增量保存路径生成的 outline 含正确 iter_count

#### 验证方法
```bash
# 手动跑一次 _save_incremental，检查 outline 输出
python3 -c "
# 模拟调用（需 builder / event_bus mock，简化为读现有文件验证逻辑）
import json
iter_idx = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669+iter_index.json'))
items_count_scout = len(iter_idx.get('scout', []))
print(f'scout iter count in iter_index: {items_count_scout}')
print('outline 应反映此数字')
"
```

#### 代码质量检查
- [ ] 复用已有变量，不重复读
- [ ] 无静默失败：save_outline_sidecar 内部已有 try/except，外层不再 swallow

#### Review 检查
- [ ] DoD 满足
- [ ] 实际跑一次 NAS run 验证 outline 正确（手动）

---

### P1-T06: 改 `test_outline_compute.py` 适配新签名

**Phase**: P1
**预估**: ~15 分钟
**依赖**: P1-T02
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
现有测试不传 iter_index 参数，需要更新。同时保留旧测试（验证向后兼容）。

#### 代码计划
- **`harness/persistence/test_outline_compute.py`** (修改)
  - 所有现有测试调用加 `iter_index=None`（显式说明用 fallback）
  - 不删除现有断言（向后兼容验证）

#### 产出标准
- [ ] 所有现有测试通过
- [ ] 没有破坏旧契约

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_outline_compute.py -v 2>&1 | tail -10
# 预期：全过
```

#### 代码质量检查
- [ ] 测试意图清晰
- [ ] 不删测试（保留回归检测）

#### Review 检查
- [ ] DoD 满足

---

### P1-T07: 加测试：iter_index 驱动的多 iter outline

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P1-T06
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
新增正向测试：给 iter_index 含多 iter 数据，断言 outline 输出正确。

#### 代码计划
- **`harness/persistence/test_outline_compute.py`** (修改)
  - 加 `test_outline_with_multi_iter_index`：
    - 构造 iter_index = `{"scout": [{"iter":1,...}, {"iter":2,...}, {"iter":3,...}]}`
    - 调 compute_outline
    - 断言 scout 有 3 个 outline 条目，iter_count=3

#### 产出标准
- [ ] 测试通过
- [ ] 断言精确（iter_count / iteration 字段都验）

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_outline_compute.py::test_outline_with_multi_iter_index -v
# 预期：passed
```

#### 代码质量检查
- [ ] 测试覆盖核心场景（多 iter 是 NAS 痛点）
- [ ] fixture 构造明确（inline 或 fixture）

#### Review 检查
- [ ] DoD 满足
- [ ] 断言检查所有关键字段

---

### P1-T08: 加测试：无 iter_index 的 legacy fallback

**Phase**: P1
**预估**: ~10 分钟
**依赖**: P1-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
负向测试：无 iter_index 时 fallback 行为正确。

#### 代码计划
- **`harness/persistence/test_outline_compute.py`** (修改)
  - 加 `test_outline_fallback_no_iter_index`：iter_index=None，dag 含 3 节点 → outline 含 3 条目，每个 iter_count=1
  - 加 `test_outline_fallback_empty_iter_index`：iter_index={} 同上

#### 产出标准
- [ ] 两个测试通过
- [ ] 覆盖 None 和 {} 两种 case

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_outline_compute.py::test_outline_fallback_no_iter_index harness/persistence/test_outline_compute.py::test_outline_fallback_empty_iter_index -v
# 预期：2 passed
```

#### 代码质量检查
- [ ] 边界 case 覆盖
- [ ] 断言精确

#### Review 检查
- [ ] DoD 满足

---

## Phase 1 完成标准

- [ ] 所有 8 个任务 ✅
- [ ] outline_compute 不再扫 events buffer 算 iter_set
- [ ] 真实 NAS run 的 outline 显示正确 iter_count（scout=3, selector=6 等）
- [ ] 旧 run（无 iter_index）fallback 正常
- [ ] Release note：`docs/releases/2026-06-xx-phase-1-outline-from-iter-index.md`
