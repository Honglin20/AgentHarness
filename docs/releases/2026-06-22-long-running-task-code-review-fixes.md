# 2026-06-22 — 长耗时任务工具 Code Review 修复（13 个问题）

## 背景

基于 `superpowers:code-reviewer` agent 对 commit `c6ea52d`（长耗时任务支持 MVP）的独立审查，发现 **1 CRITICAL / 4 HIGH / 5 MEDIUM / 3 LOW** 共 13 个问题。本 PR 修复全部 13 个 + 补 8 个测试（T1-T5 + V7）。

测试：17 → **52 passed**（35 个新增覆盖 race condition / 异常路径 / payload 格式 / OOM 防御）。

---

## 修复清单

### 🔴 CRITICAL

#### C1 — `cancel_task` 与 `on_complete` race condition

**问题**：`cancel_task` 设置 `status=cancelled` 后，bash 监控线程观察到进程退出，触发 `_on_complete` 把 status 覆盖回 `failed`。UI 显示错乱，`wait_for_tasks` 可能 polled 到 cancelled 然后 failed。

**修复**：`launch_task.py:_on_complete` 开头加 race guard：
```python
existing = registry.get(task_id)
if existing is not None and existing.status in TERMINAL_STATUSES:
    return  # cancel_task already finalized
```

**测试**：`TestCancelRaceWithOnComplete` — 启动 sleep 30 → cancel → 等 0.5s 让真实 monitor 触发 → 断言 status 仍为 `cancelled`、exit_code 仍为 `-15`，且没有 emit `task.failed`。

---

### 🟠 HIGH

#### H1 — `wait_for_tasks` fan-out race（unknown 永远是 unknown）

**问题**：`_wait_for_tasks_impl` 入口一次性 partition `known`/`unknown`，并发场景下（sub_agent fan-out）后注册的 task 永远不会被等到，立即返回 `[no known tasks]`。

**修复**：poll 循环里重新 partition——每次迭代把新出现的 task 从 unknown 提升到 known。加 `unknown_grace_deadline`（1 个 poll interval）避免空 list busy-loop。

#### H2 — `TaskRegistry` 跨进程限制未文档化

**问题**：in-process only 是已知设计选择，但 docstring 没说，Phase 2 SSH/cloud backend 会撞到这堵墙。

**修复**：`task_registry.py` 模块 docstring 加 "Scope limitation (MVP)" 段，明确说明 in-process only + Phase 2 迁移路径（read-through to JSON sidecar）。

#### H3 — `launch_task` 通过字符串解析 task_id（brittle）

**问题**：`_parse_task_id` / `_parse_output_path` 解析 `spawn_background` 返回的人类可读字符串（`"task_id: bg_xxx"`）。任何格式微调（空格、i18n、prefix 改动）会静默破坏 launch_task。

**修复**：`bash.py` 新增 `BackgroundSpawnResult` dataclass，`spawn_background` 改返回结构化对象：
```python
@dataclass
class BackgroundSpawnResult:
    task_id: str
    output_path: str
    message: str    # LLM-facing ack string (bash tool 仍用这个)
    pid: int | None = None
```

bash tool 的 `run_in_background=True` 路径改为 `return spawn_background(...).message` 保持向后兼容。`launch_task` 直接消费 `.task_id` / `.output_path` / `.pid`，删除 `_parse_task_id` / `_parse_output_path` 两个解析函数。

#### H4 — `on_complete` 在 bash emit 之后调用

**问题**：bash.py `_bg_monitor` 顺序是 `emit(bash.background_completed) → on_complete() → pop()`。如果 emit 抛出（如 bus 故意 mock 抛异常测试），on_complete 永不执行，TaskRegistry 卡死在 `running`。

**修复**：把 `on_complete` 调用移到 `_emit_event` **之前**。即使后续 emit / cleanup 失败，TaskRegistry 已更新，`wait_for_tasks` 能正常观察终态。

**测试**：`TestOnCompleteException` — 用 `on_complete` 抛 RuntimeError 的 callback，断言 task 仍被从 `_bg_tasks` 清理（monitor cleanup 路径不受 callback 异常影响）。

---

### 🟡 MEDIUM

#### M1 — `cancel_task` description 把 workflow-wide 行为埋在 Note 里

**问题**：LLM 读 tool description 时容易错过 "kills ALL tasks" 的 blast radius。

**修复**：description 首句前置 `"Cancel ALL running tasks for this workflow (MVP behavior)"` + 加 `WARNING` 字样提示 sibling sub_agent 任务会被波及。

#### M2 — `task.submitted` 可能在 `task.completed` 之后发出

**问题**：原代码 `registry.register → emit(submitted)`，监控线程可能在这两步之间完成 → 事件流 `completed → submitted` 乱序。

**修复**：调换顺序为 `emit(submitted) → registry.register`。配合 C1 的 race guard，事件顺序保证正确。

#### M3 — `read_output_tail` 读整个文件（OOM 风险）

**问题**：`p.read_text()` 读整份 stdout。长时间训练产生 100MB+ 日志，每 30s 心跳读一次 = OOM。

**修复**：改用 seek-from-end：
```python
with p.open("rb") as f:
    f.seek(0, 2); size = f.tell()
    read_size = min(size, max_chars * 4 + 8)  # utf-8 worst case + slack
    f.seek(size - read_size)
    raw = f.read()
text = raw.decode("utf-8", errors="replace")
# Drop partial first line if we seeked into the middle
if size > read_size and "\n" in text:
    text = text.split("\n", 1)[1]
return text[-max_chars:]
```

**测试**：`TestReadOutputTailSize` — 5MB 文件 / 小文件 / 缺失文件三场景。

#### M4 — `wait_for_tasks` docstring 撒谎（auto-raise 未实现）

**问题**：docstring 说 `expected_duration_s > 300 时 poll_interval_ms 自动调到 10s`——代码里没实现。LLM 会困惑为什么还是 2s。

**修复**：改为诚实描述：`"For multi-hour tasks, consider raising to 10s+ to reduce wakeups."`——把决策权交给 LLM/用户。

#### M5 — `TaskRecord.pid` 总是 None（dead field）

**问题**：`launch_task` 硬编码 `pid=None`，因为 `spawn_background` 没暴露 `proc.pid`。

**修复**：`BackgroundSpawnResult` 加 `pid` 字段，`spawn_background` 在返回时填入 `proc.pid`，`launch_task` 传给 `TaskRecord`。Phase 2 finer-grained cancel_task 可以用这个 pid 做单 task kill。

---

### 🟢 LOW

#### L1 — 魔法数字未命名

`500` (output_tail) 和 `60` (cmd preview) 提升为 `task_registry.OUTPUT_TAIL_CHARS` 和 `COMMAND_PREVIEW_CHARS` 常量。`task_wait.py` 改 import 使用。

#### L2 — `read_progress` 静默吞所有异常

区分 `FileNotFoundError`（预期，训练未开始）+ `JSONDecodeError`/`OSError`（debug 级 log）+ 其他（debug 级 log with exc_info）。

#### L3 — 测试 V7 缺失

原测试编号 V1-V8 但跳过 V7。补 `TestReadOutputTailSize`（V7: 验证 `read_output_tail` 在大文件下不 OOM）。

---

## 新增测试（8 个）

| 测试类 | 验证问题 | 覆盖点 |
|---|---|---|
| `TestCancelRaceWithOnComplete` (2) | C1 | cancelled 不被覆盖；只 emit `task.cancelled` 不 emit `task.failed` |
| `TestOnCompleteException` (2) | H4 | callback 抛异常不影响 cleanup；bash tool 仍可用 |
| `TestEmitFailure` (2) | T3 | repository missing / raising 时 launch_task 仍返回 task_id |
| `TestSummaryFormat` (2) | T5 | regex 锁定 summary 行格式；header 含 terminal 计数 |
| `TestHeartbeatTailSize` 扩展 | T4 | heartbeat payload 含 `expected_remaining_sec` / `progress` 字段 |
| `TestReadOutputTailSize` (3) | V7/L1 | 5MB 文件、小文件、缺失文件 |

---

## 偏离原 review 处

- **M2 修复方式**：review 建议两个选项（emit submitted before register / 删 task.submitted）。选了前者——保留 UI 可见的 submitted 事件，但保证事件顺序正确。
- **V7 测试方式**：原计划通过 heartbeat 路径验证 output_tail 大小，但发现 bash 只在任务完成时写 output_path（运行期间为空）。改为直接测 `read_output_tail` 函数——更可靠、覆盖更全（含小文件 / 缺失文件场景）。
- **H2 修复方式**：review 建议"写 ADR 或明确 docstring"。选了 docstring——H2 是已知限制不是 bug，Phase 2 才需要 ADR。

---

## 验证

- `python -m pytest tests/tools/test_task_lifecycle.py tests/tools/test_bash.py tests/tools/test_defaults.py`：**52/52 pass**（原 41 + 11 新增 + 个别扩展）
- 所有 race condition 测试（C1/H4）在 5+ 次连续运行下稳定通过
- 无回归：`test_bash.py` 20/20 仍 pass（H3 改动 spawn_background 返回类型，bash tool path 兼容）

## Commit SHA

待 commit 后填入。

## 后续

- **Phase 2 触发条件**仍不变（训练 >24h / 切换设备 / 远端训练）
- **Phase 2 内容**更新：除了之前列的（持久化 registry + detached execution + SSHBackend.launch + dispatch_train async mode），还要加：
  - 用 H3 的 `pid` 字段做 finer-grained `cancel_task`（替 workflow-wide cancel）
  - 用 H2 的迁移路径做 registry 持久化（read-through to `runs/{run_id}/tasks/*.json`）
