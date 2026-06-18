# Phase 2b: D7 生命周期 + InflightSidecarWriter

> **目标**：D7 决策落地。sidecar 是生命周期实体（streaming → completed），刷新零丢失。
> **ADR 依据**：D7 / I7 / I8
> **预估**：1.5 天，22 个任务（最高风险 phase，拆得最细）
> **用户感知**：scout 跑 iter 3 中途刷新 → 看到已 stream 的内容（带 Live 徽章）+ WS 接续。

## 设计要点（实施前必读）

```
node.started  →  sidecar  {status: streaming,   last_seq: 100, streaming_text: "",     tool_calls: []}
                  ↓ debounced flush（500ms 或 tool_call 完成边界，atomic rename）
streaming 中  →  sidecar  {status: streaming,   last_seq: 134, streaming_text: "Hello…", tool_calls: [3个]}
                  ↓
node.completed →  sidecar {status: completed,   last_seq: 156, output_result: {...},   tool_calls: [18个]}
                  （streaming_text 清空）
```

刷新同步契约：前端 GET sidecar 拿 last_seq=N → WS connect with since_seq=N → 后端只发 seq > N 的增量。

## 任务清单

---

### P2b-T01: 设计 `InflightSidecarWriter` 接口

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P0 完成
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
写 interface 设计文档（docstring + 类型签名），不写实现。让 reviewer 先对齐接口。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (新增)
  - 完整模块 docstring：说明生命周期、debounce 策略、atomic 保证
  - `class InflightSidecarWriter` 骨架：
    - `__init__(self, run_id: str, node_id: str, iter_num: int, runs_dir: Path, debounce_ms: int = 500)`
    - `on_started(self, input_prompt: str, system_prompt: str, last_seq: int) -> None`
    - `on_text_delta(self, text: str, seq: int) -> None`
    - `on_tool_call(self, tool_call: dict, seq: int) -> None`
    - `on_tool_result(self, tool_name: str, result: Any, seq: int) -> None`
    - `finalize(self, output_result: Any, last_seq: int) -> None`
    - `mark_failed(self, error: str, last_seq: int) -> None`
    - `mark_interrupted(self, last_seq: int) -> None`
    - `flush(self) -> None` (force flush，用于 test)
  - 全部 raise NotImplementedError

#### 产出标准
- [ ] 接口完整（生命周期全覆盖）
- [ ] docstring 说明每个方法的触发时机
- [ ] 类型注解完整

#### 验证方法
```bash
python3 -c "
from harness.persistence.sidecar_writer import InflightSidecarWriter
w = InflightSidecarWriter('r1', 'scout', 1, '/tmp')
methods = ['on_started', 'on_text_delta', 'on_tool_call', 'on_tool_result', 'finalize', 'mark_failed', 'mark_interrupted', 'flush']
for m in methods:
    try: getattr(w, m)()
    except NotImplementedError: print(f'{m}: skeleton OK')
"
```

#### 代码质量检查
- [ ] 单一职责：writer 只管一个 (run, node, iter) 的生命周期
- [ ] 开闭原则：新增事件类型加新方法，不改现有签名
- [ ] 命名达意：on_* 表示被动接收事件，mark_* 表示状态变更

#### Review 检查
- [ ] DoD 满足
- [ ] 接口覆盖所有生命周期阶段
- [ ] 类型注解 review

---

### P2b-T02: 建 `sidecar_writer.py` 骨架

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
完成类的字段定义和 __init__，但方法体仍 raise NotImplementedError。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 __init__：初始化所有字段
    - `self.path = runs_dir / f"{run_id}+iters+{node_id}+{iter_num}.json"`
    - `self.streaming_text = ""`
    - `self.tool_calls = []`
    - `self.last_seq = 0`
    - `self.input_prompt / system_prompt = None`
    - `self.last_flush_at = 0.0`
    - `self.debounce_s = debounce_ms / 1000.0`
    - `self.dirty = False`

#### 产出标准
- [ ] __init__ 完整
- [ ] 路径构造正确（和现有 sidecar 文件命名一致）
- [ ] 其他方法仍 NotImplementedError

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_writer import InflightSidecarWriter
w = InflightSidecarWriter('r1', 'scout', 1, Path('/tmp'))
print('path:', w.path)
print('streaming_text:', repr(w.streaming_text))
"
# 预期：path: /tmp/r1+iters+scout+1.json
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 命名达意
- [ ] 无 magic number：debounce_ms 默认值有 docstring

#### Review 检查
- [ ] DoD 满足

---

### P2b-T03: 实现 writer 状态字段（per (run_id, node_id, iter_num)）

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T02
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
writer 状态字段的更新逻辑（不写盘，只更新内存）。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 私有方法 `_update_state()`：刷新 last_seq、dirty flag
  - helper: `_build_sidecar_data(status: str, **extras) -> dict`：从当前状态构造 sidecar dict

#### 产出标准
- [ ] helper 能正确构造 sidecar dict
- [ ] 字段顺序和 schema 一致

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_writer import InflightSidecarWriter
w = InflightSidecarWriter('r1', 'scout', 1, Path('/tmp'))
w.streaming_text = 'hello'
w.tool_calls = [{'tool_name': 'X'}]
w.last_seq = 42
data = w._build_sidecar_data('streaming')
print(data)
"
# 预期：含 status=streaming, streaming_text='hello', tool_calls=[...], last_seq=42
```

#### 代码质量检查
- [ ] 单一职责

#### Review 检查
- [ ] DoD 满足

---

### P2b-T04: 实现 `on_text_delta(text, seq)` handler

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
接收 text_delta 事件，累积到 streaming_text，更新 last_seq，触发 debounced flush。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `on_text_delta`:
    ```python
    self.streaming_text += text
    self.last_seq = max(self.last_seq, seq)
    self.dirty = True
    self._maybe_flush()
    ```

#### 产出标准
- [ ] 多次调用累积 text
- [ ] last_seq 单调递增
- [ ] 不立即 flush（debounced）

#### 验证方法
```bash
# 见 P2b-T18 完整测试
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 边界：text 为空字符串时不更新 dirty（避免无意义 flush）

#### Review 检查
- [ ] DoD 满足

---

### P2b-T05: 实现 `on_tool_call(tool_call, seq)` handler

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
tool_call 事件追加到 tool_calls，触发**立即 flush**（tool_call 是语义边界）。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `on_tool_call`:
    ```python
    self.tool_calls.append(tool_call)
    self.last_seq = max(self.last_seq, seq)
    self.dirty = True
    self.flush()  # tool_call 是边界，立即 flush
    ```

#### 产出标准
- [ ] tool_call 立即触发 flush（不等 debounce）
- [ ] tool_calls 累积正确

#### 验证方法
```bash
# 见 P2b-T18
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 语义清晰：tool_call 边界立即 flush 是设计决策（docstring 解释）

#### Review 检查
- [ ] DoD 满足
- [ ] 立即 flush 的决策合理（vs 等 debounce）

---

### P2b-T06: 实现 `on_tool_result(result, seq)` handler

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T05
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
tool_result 事件填充最近一个 tool_call 的 result 字段。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `on_tool_result`:
    ```python
    # 找最近一个匹配 tool_name 且 result=None 的 tool_call
    for tc in reversed(self.tool_calls):
        if tc.get('tool_name') == tool_name and 'tool_result' not in tc:
            tc['tool_result'] = result
            break
    self.last_seq = max(self.last_seq, seq)
    self.dirty = True
    self.flush()
    ```

#### 产出标准
- [ ] tool_result 正确匹配到 tool_call
- [ ] 找不到匹配时不抛（defensive，可能乱序）

#### 验证方法
```bash
# 见 P2b-T18
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 边界：找不到匹配 tool_call 时如何处理（log warn 或 silent？）

#### Review 检查
- [ ] DoD 满足

---

### P2b-T07: 实现 `node.started` 初始 sidecar 写入

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
node.started 触发时立即写初始 sidecar（status=streaming, streaming_text=""），让刷新立刻能看到"node 已经开始"。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `on_started`:
    ```python
    self.input_prompt = input_prompt
    self.system_prompt = system_prompt
    self.last_seq = last_seq
    data = self._build_sidecar_data('streaming')
    save_iter_sidecar_safe(...)  # 立即写
    self.last_flush_at = time.time()
    ```

#### 产出标准
- [ ] node.started 后立即有 sidecar 文件
- [ ] status=streaming, streaming_text=""
- [ ] last_seq 来自 event_bus

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_writer import InflightSidecarWriter
import tempfile
with tempfile.TemporaryDirectory() as td:
    w = InflightSidecarWriter('r1', 'scout', 1, Path(td))
    w.on_started(input_prompt='hello', system_prompt='sys', last_seq=100)
    import json
    data = json.load(open(w.path))
    print('status:', data['status'])
    print('streaming_text:', repr(data.get('streaming_text', 'MISSING')))
    print('last_seq:', data.get('last_seq'))
"
# 预期：status: streaming / streaming_text: '' / last_seq: 100
```

#### 代码质量检查
- [ ] 单一职责
- [ ] Fail loud：save_iter_sidecar_safe 返回 False 时 log

#### Review 检查
- [ ] DoD 满足

---

### P2b-T08: 实现 debounced flush（500ms 定时器）

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T04
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
text_delta 不立即 flush，500ms 内的多次 delta 合并为一次写盘。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `_maybe_flush()`:
    ```python
    def _maybe_flush(self):
        if not self.dirty:
            return
        now = time.time()
        if now - self.last_flush_at < self.debounce_s:
            return  # 还在 debounce 窗口内
        self.flush()
    ```
  - 实现 `flush()`:
    ```python
    def flush(self):
        if not self.dirty:
            return
        data = self._build_sidecar_data('streaming')
        save_iter_sidecar_safe(...)
        self.last_flush_at = time.time()
        self.dirty = False
    ```

#### 产出标准
- [ ] 500ms 内多次更新只 flush 一次
- [ ] flush 后 dirty 重置

#### 验证方法
```bash
# 见 P2b-T18
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 性能：debounce 避免高频写盘
- [ ] Fail loud：flush 失败时 log（不阻塞后续 delta）

#### Review 检查
- [ ] DoD 满足
- [ ] debounce 策略合理（500ms 不是 magic number，docstring 解释）

---

### P2b-T09: 实现 atomic rename on flush

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T08
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
flush 内部用 sidecar_io.save_iter_sidecar_safe（已含 atomic rename）。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - flush / on_started / finalize 都走 save_iter_sidecar_safe
  - 不直接调 atomic_write_json（统一走 safe 路径）

#### 产出标准
- [ ] 所有写盘路径走 save_iter_sidecar_safe
- [ ] 不出现 .tmp 残留文件

#### 验证方法
```bash
# 见 P2b-T19
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 一致性：所有写盘走同一 helper

#### Review 检查
- [ ] DoD 满足

---

### P2b-T10: 实现 `finalize()` on `node.completed`

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T07, P2b-T08
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
node.completed 时把 streaming_text 清空、output_result 填充、status=completed，最后一次写盘。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `finalize`:
    ```python
    def finalize(self, output_result, last_seq):
        self.output_result = output_result
        self.streaming_text = ''  # 清空
        self.last_seq = max(self.last_seq, last_seq)
        self.ended_at = int(time.time() * 1000)
        self.status = 'completed'
        data = self._build_sidecar_data('completed')
        save_iter_sidecar_safe(...)
        self.dirty = False
    ```

#### 产出标准
- [ ] finalize 后 sidecar status=completed
- [ ] streaming_text 清空
- [ ] output_result 填充
- [ ] duration_ms 计算正确（ended_at - started_at）

#### 验证方法
```bash
python3 -c "
from pathlib import Path
from harness.persistence.sidecar_writer import InflightSidecarWriter
import tempfile, json
with tempfile.TemporaryDirectory() as td:
    w = InflightSidecarWriter('r1', 'scout', 1, Path(td))
    w.on_started(input_prompt='p', system_prompt='s', last_seq=100)
    w.on_text_delta('hello ', 101)
    w.on_text_delta('world', 102)
    w.finalize(output_result={'summary': 'done'}, last_seq=110)
    data = json.load(open(w.path))
    print('status:', data['status'])
    print('streaming_text:', repr(data.get('streaming_text')))
    print('output_result:', data.get('output_result'))
"
# 预期：status: completed / streaming_text: '' / output_result: {'summary': 'done'}
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 一致性：streaming → completed 字段切换明确

#### Review 检查
- [ ] DoD 满足
- [ ] streaming_text 清空决策合理（不保留在 completed sidecar）

---

### P2b-T11: 实现 `mark_failed()` on `node.failed`

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T10
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
node.failed 时 status=failed，保留 streaming_text + tool_calls 作为 debug 证据。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `mark_failed`:
    ```python
    def mark_failed(self, error, last_seq):
        self.error = error
        self.last_seq = max(self.last_seq, last_seq)
        self.ended_at = int(time.time() * 1000)
        data = self._build_sidecar_data('failed', error=error)
        save_iter_sidecar_safe(...)
        self.dirty = False
    ```

#### 产出标准
- [ ] status=failed
- [ ] streaming_text 和 tool_calls 保留（debug 用）
- [ ] error 字段记录失败原因

#### 验证方法
```bash
# 见 P2b-T21
```

#### 代码质量检查
- [ ] 单一职责
- [ ] Fail loud：error 字段必填

#### Review 检查
- [ ] DoD 满足

---

### P2b-T12: 实现 `mark_interrupted()` 兜底

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T11
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
后端重启后发现 sidecar 还在 streaming（ended_at=null + 进程没在跑），标记为 interrupted。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 实现 `mark_interrupted`:
    ```python
    def mark_interrupted(self, last_seq):
        # 类似 mark_failed 但语义是"进程崩溃"
        ...
    ```
- **`harness/engine/lifecycle.py`** 或 startup hook（新增/修改）：
  - 启动时扫描所有 streaming sidecar（进程重启后），调 mark_interrupted

#### 产出标准
- [ ] mark_interrupted 写 status=interrupted
- [ ] startup hook 扫描并修复 streaming sidecar

#### 验证方法
```bash
# 手动构造一个 streaming sidecar，重启 server，验证自动标记
python3 -c "
import json
p = '/tmp/test_interrupted.json'
with open(p, 'w') as f:
    json.dump({'iter': 1, 'node_id': 'scout', 'status': 'streaming', 'last_seq': 50}, f)
"
# 重启 server（如能模拟），检查 sidecar 状态
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 边界：扫描时进程真在跑的情况（避免误标）— 通过 PID file 或 lock 判断

#### Review 检查
- [ ] DoD 满足
- [ ] 误判风险讨论（review 确认 PID 检查策略）

---

### P2b-T13: 把 writer 订阅到 event_bus

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T04 ~ T11
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
writer 通过 event_bus 订阅事件，按 (run_id, node_id, iter) 路由到对应 writer 实例。

#### 代码计划
- **`harness/persistence/sidecar_writer.py`** (修改)
  - 加 `InflightWriterRegistry` 类：管理 active writers 的注册表
    - `get_or_create(run_id, node_id, iter_num) -> InflightSidecarWriter`
    - `cleanup(run_id, node_id, iter_num)` (finalize 后移除)
  - 加 `route_event_to_writer(event: dict) -> None`：按事件类型分发
- **`harness/engine/builder.py`** 或类似入口（修改）
  - 在 event_bus subscribe 时加 writer router
  - node.started → 创建 writer + 调 on_started
  - agent.text_delta → 调 on_text_delta
  - agent.tool_call / tool_result → 对应方法
  - node.completed → finalize + cleanup
  - node.failed → mark_failed + cleanup

#### 产出标准
- [ ] 真实跑一次 NAS workflow，scout 跑的过程中 sidecar 文件实时更新（streaming 状态）
- [ ] node 完成后 sidecar status=completed

#### 验证方法
```bash
# 跑 NAS workflow，scout 跑的过程中：
ls -la runs/ | grep iters
# 预期：scout 的 sidecar 文件 mtime 不断更新

cat runs/<run_id>+iters+scout+1.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'], len(d.get('streaming_text','')))"
# 预期：streaming + 非零长度（如果 scout 还在跑）
```

#### 代码质量检查
- [ ] 单一职责：registry 管理生命周期，writer 处理单个 iter
- [ ] 开闭原则：新事件类型加新 route 分支
- [ ] 无内存泄漏：finalize 后必须 cleanup，否则 registry 无限增长

#### Review 检查
- [ ] DoD 满足
- [ ] registry cleanup 路径完整（completed / failed / interrupted）
- [ ] 并发场景：同一 (run, node, iter) 不会创建多个 writer

---

### P2b-T14: 扩展 iter_sidecar schema：加 `status` 字段

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P0-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
schema 加 status 字段（P0-T03 已经预留，本任务确认 enum 完整）。

#### 代码计划
- **`schemas/iter_sidecar.v2.schema.json`** (修改)
  - 确认 status enum: `["streaming", "completed", "failed", "interrupted"]`
  - 确认 status 是 required（D7 要求）
  - 加 default 兼容旧 sidecar（status 缺失时 validate 视为 completed）

#### 产出标准
- [ ] schema enum 完整
- [ ] 旧 sidecar（无 status）能通过校验

#### 验证方法
```bash
python3 -c "
import json, jsonschema
schema = json.load(open('schemas/iter_sidecar.v2.schema.json'))
# 旧 sidecar
old = json.load(open('runs/4a8dc827-4466-4fbf-a896-a29ed018f279+iters+scout+1.json'))
try:
    jsonschema.validate(old, schema)
    print('old OK')
except jsonschema.ValidationError as e:
    print('old FAIL:', e.message)
"
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 向后兼容

#### Review 检查
- [ ] DoD 满足

---

### P2b-T15: 扩展 iter_sidecar schema：加 `last_seq` 字段

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T14
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
schema 加 last_seq（int，>= 0）。

#### 代码计划
- **`schemas/iter_sidecar.v2.schema.json`** (修改)
  - properties 加 last_seq：`{"type": "integer", "minimum": 0}`
  - required（D7/I7 要求）
  - 旧 sidecar 无 last_seq 时 validate 应宽容（default 0 或不强制 required）

#### 产出标准
- [ ] last_seq 字段定义
- [ ] 旧 sidecar 通过校验

#### 验证方法
```bash
# 同 P2b-T14
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 向后兼容

#### Review 检查
- [ ] DoD 满足

---

### P2b-T16: 扩展 iter_sidecar schema：加 `streaming_text` 字段

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T15
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
schema 加 streaming_text（string，可空）。

#### 代码计划
- **`schemas/iter_sidecar.v2.schema.json`** (修改)
  - properties 加 streaming_text：`{"type": "string", "default": ""}`
  - 非 required（completed 状态下可以为空字符串）

#### 产出标准
- [ ] streaming_text 字段定义
- [ ] 默认空字符串

#### 验证方法
```bash
# 同 P2b-T14
```

#### 代码质量检查
- [ ] 单一职责

#### Review 检查
- [ ] DoD 满足

---

### P2b-T17: 单测：writer lifecycle (start→stream→complete)

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T13
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
端到端测试 writer 生命周期。

#### 代码计划
- **`harness/persistence/test_sidecar_writer.py`** (新增)
  - `test_full_lifecycle`：
    - on_started → on_text_delta × 3 → on_tool_call → on_tool_result → finalize
    - 验证最终 sidecar：status=completed, output_result=..., tool_calls=[...]

#### 产出标准
- [ ] 测试通过
- [ ] 断言覆盖所有字段

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_writer.py::test_full_lifecycle -v
```

#### 代码质量检查
- [ ] 测试意图清晰
- [ ] 无 flake

#### Review 检查
- [ ] DoD 满足

---

### P2b-T18: 单测：debounced flush 计时正确

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T08
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
验证 debounce 窗口内的多次 delta 只 flush 一次。

#### 代码计划
- **`harness/persistence/test_sidecar_writer.py`** (修改)
  - `test_debounce_within_window`：500ms 内 5 次 text_delta → flush 计数 1 次
  - `test_debounce_across_window`：两次 delta 间隔 600ms → flush 计数 2 次
  - 用 mock time 或 freezegun（如已装），否则用 monkey patch time.time

#### 产出标准
- [ ] 2 个测试通过
- [ ] flush 计数精确

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_writer.py -k debounce -v
```

#### 代码质量检查
- [ ] 测试不依赖真实 sleep（避免慢）
- [ ] mock 严格

#### Review 检查
- [ ] DoD 满足

---

### P2b-T19: 单测：atomic rename 不半写

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T09
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
验证写盘过程中 kill 进程，文件不半写。

#### 代码计划
- **`harness/persistence/test_sidecar_writer.py`** (修改)
  - `test_no_partial_file_on_crash`：mock save_iter_sidecar_safe 在 rename 前抛异常 → 验证 sidecar 文件不存在或仍是旧内容（不是半写）

#### 产出标准
- [ ] 测试通过
- [ ] 无 .tmp 残留

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_writer.py::test_no_partial_file_on_crash -v
```

#### 代码质量检查
- [ ] 边界 case 覆盖
- [ ] mock 严格

#### Review 检查
- [ ] DoD 满足

---

### P2b-T20: 单测：finalize 把 streaming_text 替换为 output_result

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T10
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
验证 finalize 后字段切换正确。

#### 代码计划
- **`harness/persistence/test_sidecar_writer.py`** (修改)
  - `test_finalize_clears_streaming_text`：stream 中 → finalize → streaming_text='' + output_result=...

#### 产出标准
- [ ] 测试通过

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_writer.py::test_finalize_clears_streaming_text -v
```

#### 代码质量检查
- [ ] 测试意图清晰

#### Review 检查
- [ ] DoD 满足

---

### P2b-T21: 单测：node.failed 写 status=failed

**Phase**: P2b
**预估**: ~10 分钟
**依赖**: P2b-T11
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
验证 mark_failed 路径。

#### 代码计划
- **`harness/persistence/test_sidecar_writer.py`** (修改)
  - `test_mark_failed_status`：stream 中 → mark_failed → status=failed, error=..., streaming_text 保留

#### 产出标准
- [ ] 测试通过

#### 验证方法
```bash
python3 -m pytest harness/persistence/test_sidecar_writer.py::test_mark_failed_status -v
```

#### 代码质量检查
- [ ] 测试意图清晰

#### Review 检查
- [ ] DoD 满足

---

### P2b-T22: 真机验证：scout 跑 iter 3 中途刷新看到 streaming_text

**Phase**: P2b
**预估**: ~15 分钟
**依赖**: P2b-T13, P2b-T17, 前端 D7 支持完成
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
真实跑 NAS workflow，scout 跑到一半时刷新页面，验证：
1. 看到 streaming_text 内容（带 Live 徽章）
2. WS 重连续接新 token
3. node 完成后无缝切换到 completed

#### 代码计划
- 无代码改动（前端 D7 支持由 P3-T08 验证）
- 跑 NAS，监控 sidecar 文件状态

#### 产出标准
- [ ] scout 跑 iter 中刷新 → 看到部分内容
- [ ] sidecar status=streaming 在文件中可见
- [ ] node 完成后 status=completed

#### 验证方法
```bash
# 启动 NAS（用 mock LLM 缩短时长）
# 在 scout 跑到一半时刷新浏览器
# 用 DevTools 检查：
curl 'http://localhost:8000/api/runs/<run_id>/nodes/scout/iters/3' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('status:', d['status'])
print('streaming_text len:', len(d.get('streaming_text','')))
"
# 预期：status: streaming, streaming_text 有内容
```

#### 代码质量检查
- [ ] 真机验证清单完整
- [ ] 截图 / 录屏作为 evidence

#### Review 检查
- [ ] DoD 满足
- [ ] 用户确认刷新零丢失体验

---

## Phase 2b 完成标准

- [ ] 所有 22 个任务 ✅
- [ ] InflightSidecarWriter 实现完整
- [ ] schema 含 status / last_seq / streaming_text
- [ ] 真机验证刷新零丢失
- [ ] Release note：`docs/releases/2026-06-xx-phase-2b-sidecar-lifecycle.md`
