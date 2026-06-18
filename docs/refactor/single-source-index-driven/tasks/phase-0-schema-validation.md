# Phase 0: Schema + 原子写盘 + CI lint

> **目标**：把"隐式契约"变成"显式断言"。后续 phase 的所有改动都在 schema 约束下进行。
> **ADR 依据**：D2 / D3 / R3 / I1-I9
> **预估**：0.5 天，18 个任务

## 任务清单

---

### P0-T01: 建 schemas/ 目录 + 三个 v2 schema 骨架

**Phase**: P0
**预估**: ~10 分钟
**依赖**: 无
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
为 snapshot / iter_sidecar / iter_index 三类核心数据文件建立 JSON Schema 规范，定义 v2 契约。

#### 代码计划
- **`schemas/`** (新增目录)
- **`schemas/README.md`** (新增)：说明 schema 版本管理政策（v1 兼容只读，v2 是 target）
- **`schemas/snapshot.v2.schema.json`** (新增)：空骨架，仅 `$id` + `$schema` + `title` + `type: object`
- **`schemas/iter_sidecar.v2.schema.json`** (新增)：同上
- **`schemas/iter_index.v2.schema.json`** (新增)：同上

#### 产出标准
- [ ] `schemas/` 目录存在，含 1 个 README + 3 个 schema 文件
- [ ] 每个 schema 文件 `python -c "import json; json.load(open('...'))"` 不抛错
- [ ] README 说明：v1 是只读兼容、v2 是当前 target、未来字段加在 v2 上

#### 验证方法
```bash
ls schemas/
# 预期：README.md snapshot.v2.schema.json iter_sidecar.v2.schema.json iter_index.v2.schema.json

python3 -c "import json; [json.load(open(f'schemas/{f}')) for f in ['snapshot.v2.schema.json','iter_sidecar.v2.schema.json','iter_index.v2.schema.json']]"
# 预期：无输出（成功）
```

#### 代码质量检查
- [ ] 单一职责：schema 文件只描述数据形状，不含逻辑
- [ ] 开闭原则：v2 schema 后续可扩展字段而不破坏 v1 reader
- [ ] Fail loud：无效 JSON 文件应当 parse 失败（不静默）
- [ ] 命名达意：`<entity>.v<major>.schema.json` 模式清晰

#### Review 检查
- [ ] DoD 全部满足
- [ ] 3 个 schema 文件结构一致（同样的 `$id` 命名规则）
- [ ] README 提到了"v2 是当前 target，未来变更走 major 版本"

---

### P0-T02: 写 `snapshot.v2.schema.json`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
按 D3 定义 snapshot v2 的字段约束。这是后续 P4 瘦身的 target schema，但先以当前 snapshot 字段为准（保留兼容性，P4 再裁剪）。

#### 代码计划
- **`schemas/snapshot.v2.schema.json`** (修改)：完整字段定义
  - required: `version, run_id, workflow_name, status, created_at, dag, last_seq`
  - properties: 按 ADR D3 manifest 结构（注：P4 才移除 conversation/agent_io/todo_states，所以本 schema 先允许这些字段为 optional）
  - additionalProperties: false（除明确列出的字段，禁止其他）

#### 产出标准
- [ ] required 字段全部列出
- [ ] 所有字段类型明确（string / number / array / object / null）
- [ ] additionalProperties: false（防止意外塞字段）
- [ ] 用一个现有 snapshot.json（如 `runs/753ceb5b-...+snapshot.json`）通过校验

#### 验证方法
```bash
pip install jsonschema  # 如未装
python3 -c "
import json, jsonschema
schema = json.load(open('schemas/snapshot.v2.schema.json'))
data = json.load(open('runs/753ceb5b-b5d3-4a55-b68d-9105b5797ae0+snapshot.json'))
try:
    jsonschema.validate(data, schema)
    print('OK: 753ceb5b 通过校验')
except jsonschema.ValidationError as e:
    print('FAIL:', e.message)
"
# 预期：OK 或明确指出 753ceb5b 缺哪个 required 字段
```

#### 代码质量检查
- [ ] 单一职责：schema 只描述 snapshot，不混 iter_index 字段
- [ ] 开闭原则：additionalProperties=false 强制未来扩展显式更新 schema
- [ ] Fail loud：未声明字段直接报错（不静默允许）
- [ ] 无 magic：每个 required 字段在 ADR D3 中有依据

#### Review 检查
- [ ] DoD 满足
- [ ] 真实 snapshot 文件能通过（或明确列出缺哪些字段）
- [ ] required 字段集和 ADR D3 一致

---

### P0-T03: 写 `iter_sidecar.v2.schema.json`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
按 D2 定义 iter sidecar 完整字段，含 D7 的生命周期字段（status / last_seq / streaming_text）和 P2a 的内容字段（tool_calls / todo_steps）。

#### 代码计划
- **`schemas/iter_sidecar.v2.schema.json`** (修改)：完整字段定义
  - required: `iter, node_id, status, started_at`
  - properties: `iter (int≥1), node_id (str), status (enum: streaming|completed|failed|interrupted), last_seq (int≥0), started_at (int), ended_at (int|null), duration_ms (int|null), input_prompt (str|null), system_prompt (str|null), streaming_text (str), output_result (any|null), tool_calls (array), todo_steps (array), summary (str), tokens (object|null)`
  - tool_calls item schema: `{tool_name: str, tool_args: object, tool_result: any, ts: int, seq: int}`
  - todo_steps item schema: 复用现有 todo step 结构（task_id, content, status, iteration, ...）
  - additionalProperties: false

#### 产出标准
- [ ] required 字段集和 ADR D2 一致
- [ ] status enum 包含 D7 的 4 个值
- [ ] tool_calls 和 todo_steps 都有 item schema
- [ ] 用一个现有 sidecar（如 `runs/4a8dc827-...+iters+scout+1.json`）能通过校验（旧 sidecar 缺 status 字段，schema 应允许）

#### 验证方法
```bash
python3 -c "
import json, jsonschema
schema = json.load(open('schemas/iter_sidecar.v2.schema.json'))
data = json.load(open('runs/4a8dc827-4466-4fbf-a896-a29ed018f279+iters+scout+1.json'))
# 旧 sidecar 缺 status / last_seq 字段，需 schema 允许（required 只列 iter/node_id/started_at，status 用 default）
try:
    jsonschema.validate(data, schema)
    print('OK')
except jsonschema.ValidationError as e:
    print('FAIL:', e.message)
"
```

#### 代码质量检查
- [ ] 单一职责：schema 只描述单个 (node, iter) 数据
- [ ] Fail loud：unknown 字段直接拒绝
- [ ] 边界 case：旧 sidecar 缺新字段时也能通过（required 集合最小化）

#### Review 检查
- [ ] DoD 满足
- [ ] 旧 sidecar 通过校验（向后兼容）
- [ ] status enum 值和 ADR D7 完全一致

---

### P0-T04: 写 `iter_index.v2.schema.json`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
按 D1 定义 iter_index 文件格式：`{node_id: [{iter, status, duration_ms, summary, started_at, ended_at}, ...]}`。

#### 代码计划
- **`schemas/iter_index.v2.schema.json`** (修改)
  - type: object
  - patternProperties: `^.+$` (任意 node_id 键) → array of iter entries
  - iter entry schema: `{iter: int≥1, status: str, duration_ms: int|null, summary: str, started_at: int|null, ended_at: int|null}`
  - additionalProperties: false

#### 产出标准
- [ ] 用 `runs/5c6eac84-...+iter_index.json` 通过校验
- [ ] iter entry 必填字段集：iter / status / summary
- [ ] duration_ms / started_at / ended_at 允许 null（向后兼容）

#### 验证方法
```bash
python3 -c "
import json, jsonschema
schema = json.load(open('schemas/iter_index.v2.schema.json'))
data = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669+iter_index.json'))
jsonschema.validate(data, schema); print('OK')
"
```

#### 代码质量检查
- [ ] 单一职责
- [ ] patternProperties 强制 value 是 array（不允许其他形状）

#### Review 检查
- [ ] DoD 满足
- [ ] 真实 iter_index 通过校验

---

### P0-T05: 建 `harness/persistence/sidecar_io.py` 骨架

**Phase**: P0
**预估**: ~10 分钟
**依赖**: 无
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
新建 sidecar I/O 工具模块，集中所有 sidecar / snapshot 的原子写盘逻辑。后续 P2b 的 InflightSidecarWriter 也基于此。

#### 代码计划
- **`harness/persistence/__init__.py`** (新增，若不存在)：导出公开 API
- **`harness/persistence/sidecar_io.py`** (新增)
  - 模块 docstring：说明用途 + atomic write 契约
  - 函数签名（仅签名，不实现）：
    - `atomic_write_json(path: Path, data: dict) -> None`
    - `verify_write(path: Path, expected: dict) -> bool`
    - `save_iter_sidecar_safe(run_id: str, node_id: str, iter_num: int, data: dict, max_retries: int = 1) -> bool`
  - 全部 raise NotImplementedError

#### 产出标准
- [ ] 模块文件存在，含完整 docstring 和函数签名
- [ ] 所有函数 raise NotImplementedError（实现留给 P0-T06/T07/T08）
- [ ] `from harness.persistence import sidecar_io` 可导入

#### 验证方法
```bash
python3 -c "from harness.persistence import sidecar_io; print(sidecar_io.atomic_write_json.__doc__)"
# 预期：函数 docstring

python3 -c "from harness.persistence.sidecar_io import save_iter_sidecar_safe; save_iter_sidecar_safe('x','y',1,{})" 2>&1 | tail -1
# 预期：NotImplementedError
```

#### 代码质量检查
- [ ] 单一职责：sidecar_io 只负责"写盘 + 校验"，不订阅事件、不投影数据
- [ ] 开闭原则：函数签名稳定，新增能力（如 batch write）加新函数而非改签名
- [ ] 命名达意：`_safe` 后缀暗示有 retry/error handling

#### Review 检查
- [ ] DoD 满足
- [ ] 函数签名和 ADR R3 / D7 决策一致（`max_retries` 参数存在）

---

### P0-T06: 实现 `atomic_write_json()`

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T05
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
实现 POSIX atomic rename 写盘：写到 `path.tmp`，rename 到 `path`。保证文件要么是旧内容要么是新内容，永不半写。

#### 代码计划
- **`harness/persistence/sidecar_io.py`** (修改)
  - 实现 `atomic_write_json(path, data)`:
    1. `tmp = path.with_suffix(path.suffix + '.tmp')`
    2. `tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))`
    3. `os.replace(tmp, path)` （POSIX 原子）
    4. 异常：tmp 文件清理（finally 块）

#### 产出标准
- [ ] 中断测试：写盘过程中 kill 进程，文件不半写（要么旧要么新）
- [ ] tmp 文件不残留（成功 / 失败路径都清理）
- [ ] unicode 内容正确写入（`ensure_ascii=False`）

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_io import atomic_write_json
p = Path('/tmp/test_atomic.json')
atomic_write_json(p, {'中文': '测试', 'seq': 42})
print(p.read_text())
p.unlink()
"
# 预期：JSON 包含中文字符 + 缩进
```

#### 代码质量检查
- [ ] Fail loud：写盘失败 raise，不返回 None
- [ ] 无静默 except：所有 except 都 re-raise 或 finally 清理
- [ ] 无 magic number：tmp 后缀 `.tmp` 提取为常量
- [ ] 边界 case：父目录不存在时（raise FileNotFoundError 明确报错，不静默 mkdir）

#### Review 检查
- [ ] DoD 满足
- [ ] 代码 review 同意 tmp 文件清理逻辑
- [ ] 没有用 `os.rename`（应该用 `os.replace`，POSIX 上原子且 overwrite）

---

### P0-T07: 实现 `verify_write()`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T06
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
写盘后立即 read-back 校验，防止磁盘满 / 权限问题导致 silent corruption。

#### 代码计划
- **`harness/persistence/sidecar_io.py`** (修改)
  - 实现 `verify_write(path, expected) -> bool`:
    1. 检查 `path.exists()` and `path.stat().st_size > 0`
    2. 读回 + `json.loads`
    3. 比对关键字段（不要求 byte-equal，只要求结构等价）：用 `==` 直接比 dict

#### 产出标准
- [ ] 正常 case：写后 verify 返回 True
- [ ] 磁盘满模拟（mock write 失败）：verify 返回 False
- [ ] 不抛异常，只返回 bool（让 caller 决定如何处理）

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_io import atomic_write_json, verify_write
p = Path('/tmp/test_verify.json')
data = {'x': 1}
atomic_write_json(p, data)
print('verify ok:', verify_write(p, data))
print('verify mismatched:', verify_write(p, {'x': 2}))
p.unlink()
"
# 预期：verify ok: True / verify mismatched: False
```

#### 代码质量检查
- [ ] 单一职责：只做校验，不做修复
- [ ] Fail loud：返回 False 时 caller 必须 log（在 P0-T08 实现）
- [ ] 无静默 except：所有 except 捕获并返回 False（不算"静默"因为 caller 显式处理）

#### Review 检查
- [ ] DoD 满足
- [ ] 不抛异常的设计是否合理（review 确认）

---

### P0-T08: 实现 `save_iter_sidecar_safe()` (R3 决策)

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T06, P0-T07
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
R3 决策落地：sidecar 写盘失败 retry 1 次 + log loud + 不 raise + 写后验证。统一所有 sidecar 写入路径。

#### 代码计划
- **`harness/persistence/sidecar_io.py`** (修改)
  - 实现 `save_iter_sidecar_safe(run_id, node_id, iter_num, data, max_retries=1)`:
    1. 计算 `path = <runs_dir>/{run_id}+iters+{node_id}+{iter_num}.json`
    2. 尝试 `atomic_write_json(path, data)`
    3. `verify_write(path, data)`，若失败：
       - 若 `retries < max_retries`：retry
       - 否则：log WARNING 含 run_id/node_id/iter_num + 返回 False
    4. 成功返回 True
  - 注：`<runs_dir>` 通过依赖注入或 module-level helper 解析（避免 hardcode）

#### 产出标准
- [ ] 正常写盘：返回 True，无 log
- [ ] 写盘失败 + retry 成功：返回 True，无 WARNING
- [ ] 写盘失败 + retry 仍失败：返回 False，log WARNING（含完整路径）
- [ ] 不 raise（业务不阻塞）

#### 验证方法
```bash
# 单测见 P0-T14
python3 -c "
import logging, tempfile
from pathlib import Path
from unittest.mock import patch
from harness.persistence.sidecar_io import save_iter_sidecar_safe

with tempfile.TemporaryDirectory() as td:
    with patch('harness.persistence.sidecar_io._runs_dir', Path(td)):
        ok = save_iter_sidecar_safe('r1', 'scout', 1, {'iter': 1})
        print('normal:', ok)
        # 模拟失败：把 path 改成不存在的目录
        with patch('harness.persistence.sidecar_io._runs_dir', Path('/nonexistent/xyz')):
            ok2 = save_iter_sidecar_safe('r1', 'scout', 1, {'iter': 1})
            print('failed:', ok2)
"
# 预期：normal: True / failed: False + WARNING log
```

#### 代码质量检查
- [ ] 单一职责：只负责 sidecar 写盘安全，不涉及业务语义
- [ ] Fail loud：失败时 log WARNING（不是 ERROR，因为是观测层）
- [ ] 无静默 except：except 都进入 retry / log 流程
- [ ] 无 magic number：max_retries 默认值有 docstring 解释
- [ ] 可测试：依赖注入 runs_dir，不 hardcode

#### Review 检查
- [ ] DoD 满足
- [ ] log message 含足够 debug 信息（run_id / node_id / iter_num / path）
- [ ] retry 策略和 ADR R3 一致

---

### P0-T09: 把 `_save_incremental` 改用 `save_iter_sidecar_safe`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T08
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
替换现有 `get_run_store().save_iter_sidecar()` 直调，统一走 R3 安全路径。

#### 代码计划
- **`harness/engine/incremental_save.py`** (修改)
  - line 127: `get_run_store().save_iter_sidecar(wid, node_id, iter_num, iter_data)` →
    `from harness.persistence.sidecar_io import save_iter_sidecar_safe`
    `save_iter_sidecar_safe(wid, node_id, iter_num, iter_data)`
  - 保留 `get_run_store().update_iter_index(...)` 调用（不变）
  - 移除外层 try/except 的 swallow（因为 save_iter_sidecar_safe 不 raise），改为检查返回值

#### 产出标准
- [ ] `_save_incremental` 在写 sidecar 失败时 log WARNING，但不阻塞 iter_index 更新
- [ ] 现有所有增量保存路径不受影响（regression test 通过）

#### 验证方法
```bash
python3 -m pytest harness/engine/test_incremental_save.py -v 2>&1 | tail -20
# 如无此 test 文件，手动跑：
python3 -m pytest harness/engine/ -v 2>&1 | tail -20
```

#### 代码质量检查
- [ ] 单一职责：_save_incremental 不再关心 retry 逻辑
- [ ] 无静默 except：移除原 `except Exception: logger.warning(...)` 的 swallow

#### Review 检查
- [ ] DoD 满足
- [ ] 现有 incremental_save 测试通过
- [ ] 失败路径有 log（manual 验证 mock 一下）

---

### P0-T10: 建 `harness/persistence/validate.py` 骨架

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T02, P0-T03, P0-T04
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
schema 校验 helper，写盘前 validate（fail loud），读盘后 validate（detect corruption）。

#### 代码计划
- **`harness/persistence/validate.py`** (新增)
  - 函数签名（仅签名）：
    - `validate_snapshot(data: dict) -> list[str]`  # 返回错误列表，空表示 OK
    - `validate_iter_sidecar(data: dict) -> list[str]`
    - `validate_iter_index(data: dict) -> list[str]`
  - 全部 raise NotImplementedError
  - helper: `_load_schema(name: str) -> dict`

#### 产出标准
- [ ] 模块导入正常
- [ ] 3 个函数签名定义
- [ ] 三个函数都 raise NotImplementedError

#### 验证方法
```bash
python3 -c "
from harness.persistence.validate import validate_snapshot, validate_iter_sidecar, validate_iter_index
for f in [validate_snapshot, validate_iter_sidecar, validate_iter_index]:
    try: f({})
    except NotImplementedError: print(f'{f.__name__}: OK (skeleton)')
"
```

#### 代码质量检查
- [ ] 单一职责：validate 只校验，不修改数据
- [ ] Fail loud：返回 list[str] 让 caller 决定，但实现内不静默吞错
- [ ] 命名达意：返回 errors 而非 raise，让批量校验（CI lint）能汇总报告

#### Review 检查
- [ ] DoD 满足
- [ ] 函数签名和任务 P0-T11/T12/T13 衔接

---

### P0-T11: 实现 `validate_snapshot()`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T10
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
用 P0-T02 的 schema 校验 snapshot 数据。

#### 代码计划
- **`harness/persistence/validate.py`** (修改)
  - 实现 `_load_schema('snapshot.v2')`：从 `schemas/snapshot.v2.schema.json` 读
  - 实现 `validate_snapshot(data)`：
    1. `_load_schema` 加载 schema（cache）
    2. 用 `jsonschema.Draft7Validator.iter_errors` 收集所有错误
    3. 返回 `[str(e.message) + ' at ' + e.path for e in errors]`

#### 产出标准
- [ ] 合法 snapshot → 返回 []
- [ ] 缺 required 字段 → 返回非空 list，描述具体错误
- [ ] 多错误一次返回全部（不是 fail-fast）

#### 验证方法
```bash
python3 -c "
import json
from harness.persistence.validate import validate_snapshot
data = json.load(open('runs/753ceb5b-b5d3-4a55-b68d-9105b5797ae0+snapshot.json'))
errs = validate_snapshot(data)
print('errors:', errs if errs else 'none')
"
# 预期：errors: none 或具体字段问题
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 开闭原则：schema 改动不需要改 validate 代码
- [ ] 性能：schema cache（不要每次 reload）

#### Review 检查
- [ ] DoD 满足
- [ ] iter_errors 而非 validate（一次性收集所有错误）

---

### P0-T12: 实现 `validate_iter_sidecar()`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T10
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
同 P0-T11 但针对 sidecar。

#### 代码计划
- **`harness/persistence/validate.py`** (修改)
  - 复用 P0-T11 的 `_load_schema` 模式
  - 实现 `validate_iter_sidecar(data)`

#### 产出标准
- [ ] 合法 sidecar → []
- [ ] 缺 status 字段的旧 sidecar → []（向后兼容）
- [ ] 多错误一次返回

#### 验证方法
```bash
python3 -c "
import json
from harness.persistence.validate import validate_iter_sidecar
data = json.load(open('runs/4a8dc827-4466-4fbf-a896-a29ed018f279+iters+scout+1.json'))
print('errors:', validate_iter_sidecar(data) or 'none')
"
```

#### 代码质量检查
- [ ] 同 P0-T11

#### Review 检查
- [ ] DoD 满足
- [ ] 旧 sidecar 通过校验

---

### P0-T13: 实现 `validate_iter_index()`

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T10
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
同 P0-T11 但针对 iter_index。

#### 代码计划
- **`harness/persistence/validate.py`** (修改)
  - 实现 `validate_iter_index(data)`

#### 产出标准
- [ ] 合法 iter_index → []
- [ ] 真实 iter_index 文件通过

#### 验证方法
```bash
python3 -c "
import json
from harness.persistence.validate import validate_iter_index
data = json.load(open('runs/5c6eac84-f233-49dc-9b9e-27897aeb6669+iter_index.json'))
print('errors:', validate_iter_index(data) or 'none')
"
```

#### 代码质量检查
- [ ] 同 P0-T11

#### Review 检查
- [ ] DoD 满足

---

### P0-T14: 单测 `test_sidecar_io.py`

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T06, P0-T07, P0-T08
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
覆盖 atomic_write_json / verify_write / save_iter_sidecar_safe 的关键路径。

#### 代码计划
- **`harness/persistence/test_sidecar_io.py`** (新增)
  - 测试用例：
    - `test_atomic_write_creates_file`：正常写入
    - `test_atomic_write_unicode`：中文 / emoji
    - `test_atomic_write_no_residue_tmp`：tmp 文件清理
    - `test_verify_write_ok`：写后 verify True
    - `test_verify_write_mismatch`：expected 不匹配返回 False
    - `test_save_iter_sidecar_safe_normal`：正常返回 True
    - `test_save_iter_sidecar_safe_retry_then_succeed`：第一次 fail，retry 成功
    - `test_save_iter_sidecar_safe_all_fail`：retry 也失败，返回 False + log WARNING
    - `test_save_iter_sidecar_safe_no_raise`：失败不抛异常

#### 产出标准
- [ ] 9 个测试用例全过
- [ ] 覆盖正常 + 失败 + 边界 case
- [ ] retry 测试用 mock 模拟第一次失败

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_io.py -v
# 预期：9 passed
```

#### 代码质量检查
- [ ] 测试意图清晰：每个用例 docstring 说明验证什么 invariant
- [ ] 无 flake：mock 严格，不依赖真实文件系统（用 tmp_path fixture）
- [ ] 失败信息可读：assert 信息含上下文

#### Review 检查
- [ ] DoD 满足
- [ ] 9 个 case 都有 docstring
- [ ] retry 测试逻辑正确（不是真 sleep）

---

### P0-T15: 单测 `test_validate.py`

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T11, P0-T12, P0-T13
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
覆盖三个 validate 函数。每个函数 3 个用例（OK / 缺字段 / 多字段）。

#### 代码计划
- **`harness/persistence/test_validate.py`** (新增)
  - 9 个测试用例（3 函数 × 3 场景）
  - 用 fixture 加载真实 snapshot / sidecar / iter_index 文件作为 OK 用例

#### 产出标准
- [ ] 9 个测试全过
- [ ] OK 用例使用真实文件
- [ ] 失败用例构造明确（fixture 或 inline）

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_validate.py -v
# 预期：9 passed
```

#### 代码质量检查
- [ ] 同 P0-T14
- [ ] 真实文件 fixture 放 `tests/fixtures/`（不污染 runs/）

#### Review 检查
- [ ] DoD 满足
- [ ] OK 用例确实从真实文件加载（不是 inline 构造）

---

### P0-T16: 建 `scripts/lint_runs.py`

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T11, P0-T12, P0-T13
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
CI / 手动运行的脚本，扫描 `runs/` 目录，对每个 run 校验 I1-I9 不变量，输出违规报告。

#### 代码计划
- **`scripts/lint_runs.py`** (新增)
  - CLI: `python scripts/lint_runs.py [--runs-dir runs] [--run-id <id>]`
  - 默认扫描整个 runs/，可指定单个 run
  - 输出格式：human-readable（终端彩色 + 详细路径）+ exit code（0 OK / 1 有违规）
  - 骨架：扫描目录、按 run_id 分组、调 validate_* + 不变量检查（实现留 P0-T17）

#### 产出标准
- [ ] CLI 可运行，输出每个 run 的检查结果汇总
- [ ] exit code 正确（0/1）
- [ ] `--help` 输出完整

#### 验证方法
```bash
python3 scripts/lint_runs.py --help
# 预期：usage 输出

python3 scripts/lint_runs.py --run-id 5c6eac84-f233-49dc-9b9e-27897aeb6669
# 预期：该 run 的 schema 校验 + 不变量检查报告
```

#### 代码质量检查
- [ ] 单一职责：lint 脚本只做检查，不做修复
- [ ] Fail loud：违规时 exit 1，CI 能 fail
- [ ] 可扩展：新增不变量只需在 P0-T17 加一个函数

#### Review 检查
- [ ] DoD 满足
- [ ] CLI 体验良好（--help 详细，错误信息可执行）

---

### P0-T17: 在 lint_runs.py 实现 I1-I9 检查

**Phase**: P0
**预估**: ~15 分钟
**依赖**: P0-T16
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
实现 ADR § 不变量 I1-I9 的检查函数。

#### 代码计划
- **`scripts/lint_runs.py`** (修改)
  - 加 check 函数：
    - `check_i1_iter_index_matches_files(run_id) -> list[str]`
    - `check_i3_latest_iter_consistency(run_id) -> list[str]`
    - `check_i6_snapshot_size(run_id) -> list[str]`
    - `check_i7_sidecar_has_last_seq(run_id) -> list[str]`（注：P2b 之前的 sidecar 无 last_seq，warn 不 error）
    - `check_i8_no_partial_files(run_id) -> list[str]`（残留 .tmp 文件）
    - `check_i9_no_todo_in_snapshot(run_id) -> list[str]`（注：P4 之前的 snapshot 有 todo，warn）
  - I2/I4/I5 留作 runtime invariant（在代码层保证，不在 lint 里查）

#### 产出标准
- [ ] 6 个 check 函数实现
- [ ] 每个函数返回违规描述 list（空表示 OK）
- [ ] 在真实 runs/ 上跑，输出当前违规清单（作为 baseline）

#### 验证方法
```bash
python3 scripts/lint_runs.py
# 预期：列出当前所有 run 的违规情况（P0 baseline）
```

#### 代码质量检查
- [ ] 单一职责：每个 check 函数只验一个不变量
- [ ] Fail loud：违规清晰列出
- [ ] 兼容性：未来 phase 才生效的不变量（I7/I9）当前 warn 而非 error，避免历史 run 一直 fail

#### Review 检查
- [ ] DoD 满足
- [ ] baseline 违规清单 review（区分"已知遗留"vs"新引入"）

---

### P0-T18: 把 lint_runs.py 接入 pre-commit / CI

**Phase**: P0
**预估**: ~10 分钟
**依赖**: P0-T17
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
让 lint 在 commit / CI 自动跑，违规 PR 不能合入。

#### 代码计划
- **`.pre-commit-config.yaml`** (修改，若存在) 或 **`Makefile`** target (新增)
  - 加 `lint-runs` target：调 `python scripts/lint_runs.py`
  - 在 GitHub Actions（如有）加一步
- **`CLAUDE.md`** (修改)：在"代码质量底线"加一条"sidecar / snapshot 写盘后必须通过 lint_runs.py"

#### 产出标准
- [ ] `make lint-runs` 或 `pre-commit run lint-runs` 可运行
- [ ] CI 配置（如有）含此 step
- [ ] CLAUDE.md 提到 lint_runs 的契约

#### 验证方法
```bash
make lint-runs 2>&1 | tail -5
# 预期：lint 输出 + exit code

# 测违规检测：手动改坏一个 sidecar（拷贝到 /tmp 测试，不动 runs/）
python3 scripts/lint_runs.py --runs-dir /tmp/test-runs-broken 2>&1 | tail -5
# 预期：列出违规 + exit 1
```

#### 代码质量检查
- [ ] 不阻塞开发：baseline 违规用 warn，新引入用 error
- [ ] 可绕过：`--strict` 全 error，默认仅 error 关键不变量

#### Review 检查
- [ ] DoD 满足
- [ ] CI/pre-commit 配置 review
- [ ] CLAUDE.md 更新合理（不过度）

---

## Phase 0 完成标准

- [ ] 所有 18 个任务 ✅
- [ ] schemas/ 含 3 个 schema + README
- [ ] sidecar_io.py / validate.py 通过单测
- [ ] lint_runs.py 可运行 + 接入 CI
- [ ] baseline 违规清单记录（用于后续 phase 对照）
- [ ] Release note：`docs/releases/2026-06-xx-phase-0-schema-validation.md`
