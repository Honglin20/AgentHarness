# 2026-06-22 — Workflow Agent 长耗时后台任务支持（launch_task + wait_for_tasks）

## 背景

NAS workflow 的 optimizer agent 需要启动 DL 训练（分钟级到小时级），等训练结束后基于其输出测量精度和 ONNX 延迟。harness 已有所有基础组件——`bash run_in_background` 能 spawn 分离子进程、监控线程轮询 `proc.poll()`、事件总线有 critical/normal 优先级——**唯独缺一个关键原语：`wait_for_task`**。今天调 `bash(..., run_in_background=True)` 拿到 `task_id` 后 DAG 立即推进到下一节点，没有任何机制让 agent 阻塞等待。

**核心设计决策（用户多次澄清）**：

1. **单 agent 内同步等待**（而非拆 agent + DAG barrier 节点）——PydanticAI 工具执行期间 model 不被调用，`await asyncio.sleep` 轮询不消耗 token
2. **默认不主动杀进程**——DL 训练时长不可预测，硬编码 timeout 会把跑到 95% 的训练杀掉。`launch_task.timeout_ms` 和 `wait_for_tasks.timeout_ms` **默认都是 0**（永不杀 / 无限等）
3. **MVP 仅 in-process**——跨 session 恢复（CLI 重启后任务状态保留）留到 Phase 2
4. **不动 `train_backend.py`**——LocalBackend / SSHBackend 改动留到 Phase 2

## 改动

### 新增：`harness/tools/task_registry.py`

- `TaskRecord` dataclass：`task_id` / `status` / `exit_code` / `output_path` / `timeout_ms` / `expected_duration_s` / `progress_file` 等字段
- `TaskRegistry` 类：线程安全（`threading.Lock`），bash 监控线程写、agent 读
- 模块级 singleton `get_task_registry(workflow_id)`，按 workflow_id 索引（与 `bash._bg_tasks` 模式一致）
- 状态机：`submitted → running → completed | failed | timeout | cancelled`
- 辅助函数：`emit_task_event` / `read_progress` / `read_output_tail`

### 新增：`harness/tools/launch_task.py`

- `LaunchTaskToolFactory` → `launch_task(command, description, *, timeout_ms=0, expected_duration_s=None, progress_file=None)`
- 薄包装 `bash.spawn_background`，注入 `on_complete` 回调
- 回调在 bash 监控线程触发，根据 `exit_code` / `timed_out` / `monitor_error` 推导终态，更新 `TaskRecord` + emit `task.{status}` 事件
- 解析 `spawn_background` 返回字符串提取 `task_id` / `output_path`

### 新增：`harness/tools/task_wait.py`

- `WaitForTasksToolFactory` → `wait_for_tasks(task_ids, *, timeout_ms=0, poll_interval_ms=2000)`
  - async 工具，`await asyncio.sleep` 让出 event loop（不阻塞其他 workflow）
  - 30s 间隔发 `task.heartbeat`（含 `elapsed_sec` / `expected_remaining_sec` / `progress` / `output_tail`）
  - 返回结构化 summary：`[2/2 tasks terminal in 58.3s]` + 每个 task 的 `status` / `exit_code` / `output_path`
- `ListTasksToolFactory` → 列出本 workflow 已注册任务（debug 用）
- `CancelTaskToolFactory` → MVP 用 `cancel_process(workflow_id)` workflow 级取消（finer-grained single-task cancel 留 Phase 2，需要 `TaskRecord.pid` plumbing）

### 修改：`harness/tools/bash.py`

- `spawn_background` 加 `on_complete: Callable[[task_id, exit_code, timed_out, monitor_error], None] | None` 参数
- 监控线程在 pop 任务之前调用回调（异常 swallow，不破坏 cleanup 路径）
- `_drain_pipes_and_wait` 的 `timeout_s` 类型改为 `float | None`，`None` 表示无限等（对应 `timeout_ms=0`）

### 修改：`harness/tools/defaults.py`

- `default_tool_registry` 注册 4 个新工具，全部 Tier `DEFAULT`：`launch_task` / `wait_for_tasks` / `list_tasks` / `cancel_task`
- DEFAULT tier 数量从 5 变 9（加 filesystem MCP 共 19 个）

### 修改：`harness/extensions/bus.py`

- `CRITICAL_EVENT_TYPES` 加 6 个：`task.submitted` / `task.running` / `task.completed` / `task.failed` / `task.timeout` / `task.cancelled`
- `task.heartbeat` **故意不加**——心跳丢失不影响正确性（下一个补上），且 critical 会让 runaway training 无限增长 critical buffer
- 注释说明分级理由：丢 `task.completed` = DAG 永久卡死；丢 `task.heartbeat` = UI 30s 后自然恢复

### 新增：`workflows/long_task_demo/`

完整 demo，~30s 端到端跑通，无需 GPU：

- `workflow.json`：单 agent `train_and_eval`
- `agents/train_and_eval.md`：手把手教 LLM 的 step-by-step prompt（含反模式说明）
- `helpers/mock_train.py`：演示**正确的训练脚本契约**——`--steps` / `--out_dir` / `--progress_file` / `--measure-only`，周期写 progress、结束写 metrics.json
- `README.md`：demo 入口 + timeout 语义对比 + 场景演示

### 新增：`tests/tools/test_task_lifecycle.py`

17 个 E2E 测试覆盖 V1-V8：

- V1：短任务 launch + wait
- V2：opt-in 硬 timeout（`launch_task(timeout_ms=1000)` + sleep 30s）
- V3：失败路径（exit 7 → status=failed, exit_code=7）
- V4：Fan-out（3 个并行 sleep 2s，总墙钟 ~2s 非 ~6s）
- V5：事件优先级（critical vs normal）
- V6：长任务心跳（patch HEARTBEAT_INTERVAL_S=0.5s，断言 ≥2 次心跳）
- V8：默认无 timeout（`launch_task(timeout_ms=0)` 让任务自然完成）
- 加 `list_tasks` / `cancel_task` / 未知 task_id 处理测试

### 修改：`README.md`

5 处更新反映新机制：

1. Workflow 模式 新增"长耗时任务（launch + wait）"章节（示例代码 + timeout 对比表 + 训练脚本契约 + 能力边界）
2. 工具系统 内置工具表 加 4 行
3. 工具系统 3 层分级 DEFAULT tier 列表更新，典型场景工具数 15→19
4. 项目结构 ASCII box + 目录树 加 `launch_task, wait_for_tasks`
5. 工具路线图 移除 `Monitor`（被心跳机制覆盖），新增"已实现"小节

## 偏离 plan 处

- **跳过了 AgentDeps / server/repository 改动**：原计划给 `AgentDeps` 加 `task_registry` 字段、给 `server.repository` 加 slot、给 `builder.py` 加注入逻辑。实际用了**模块级 singleton（keyed by workflow_id）**——surgical 改动更小，工具通过 `ctx.deps.workflow_id + get_task_registry(wid)` 直接访问。TaskRegistry 单元本身是 thread-safe，不需要 Pydantic validation 的开销。
- **`cancel_task` 是 workflow 级而非 task 级**：复用现有 `cancel_process(workflow_id)`。finer-grained cancel 需要 `TaskRecord.pid` plumbing（spawn_background 目前不暴露 Popen 对象给 caller），留作 Phase 2。

## 验证

- `python -m pytest tests/tools/test_task_lifecycle.py`：**17/17 pass**
- `python -m pytest tests/tools/test_bash.py`：**20/20 pass**（无回归）
- `python -m pytest tests/tools/test_defaults.py`：**4/4 pass**
- `mock_train.py` 端到端：训练模式写 `metrics.json` + `progress.json`，`--measure-only` 写 `latency.json`
- workflow.json 加载验证：`Agents: ['train_and_eval']`，7 个工具齐全
- 工具注册一致性：`default_tool_registry()` 实际 11 个 built-in，与 README 表格吻合

## 能力边界（重要）

- ✅ 分钟级到数小时训练（前提：harness ui 或 CLI 进程不退出）
- ⚠️ 数小时训练会触发 LLM prompt cache miss（Anthropic 5min TTL），下一轮调用约 10× 成本——成本问题，非功能问题
- ❌ 跨 session 恢复（CLI 重启后任务状态丢失）→ Phase 2
- ❌ 远端训练（SSHBackend.launch / CloudBackend）→ Phase 2

## Phase 2 触发条件

以下任一场景出现时启动 Phase 2：

- 训练 >24h（进程存活成本变高，CLI 进程要持续占着终端）
- 需在训练期间切换设备 / 重启 harness
- 训练跑在远端（SSH / cloud），本地仅调度

Phase 2 内容：持久化 registry（`runs/{run_id}/tasks/{task_id}.json`）+ detached 执行（`os.setsid`）+ `SSHBackend.launch()` + `dispatch_train(mode="launch")` + 跨 session re-attach。

## 设计决策记录

### Q: 为什么 LLM API 不会因为 tool 执行几小时而超时？

A: Anthropic Messages API 的 tool 交互是**两次独立的 HTTP 请求**：

```
[Req 1] POST /v1/messages → tool_use（LLM 生成完就关连接）
       ↓ 几小时在客户端执行 tool，无 HTTP 连接挂着
[Req 2] POST /v1/messages（带 tool_result）→ 最终响应
```

工具执行发生在两次 HTTP 请求之间，在客户端。`httpx.Timeout(600.0)` 只约束单次 HTTP round-trip。

代码层面已验证 `harness/engine/llm_executor.py:228-242` 的 `await self._handle_call_tools(...)` 无 `asyncio.wait_for` 包裹、无 wall-clock timeout。`UsageLimits(request_limit=200)` 只限制 LLM 请求数，不限 tool 执行时长。`sub_agent.py:138` 的 `await child.run(...)` 已是先例（分钟级起步）。

### Q: 为什么 `launch_task` 默认 `timeout_ms=0`？

A: DL 训练时长普遍 >1h 且事先不可预测（数据量、模型大小、GPU 型号、batch size 都影响）。硬编码 timeout 是危险的——可能把跑到 95% 的训练杀掉，浪费几小时 GPU 时间。

`timeout_ms > 0` 仅作为 opt-in 安全网：

- 夜间批处理：超过 N 小时杀掉释放资源
- 实验性训练：怀疑脚本可能死循环
- 共享 GPU：多人约定单任务上限

### Q: `task.heartbeat` 为什么是 normal 不是 critical？

A: 心跳丢失不影响正确性（下一个心跳会补上），完成事件丢失会让 DAG 永久卡死。critical 事件永不淘汰（buffer 无上限），normal 事件 FIFO。如果心跳是 critical，runaway training 会让 critical buffer 无限增长。

## Commit SHA

待 commit 后填入。

## 后续

- **Phase 2**：持久化 registry + detached execution + SSHBackend.launch + dispatch_train async mode
- **Phase 3**：CloudBackend.launch（基于 `autodl_api.wait_running` 轮询模式）+ 前端实时任务面板
- **NAS workflow 接入**：`workflows/nas/agents/baseline_runner.md` 等训练相关 agent prompt 更新，改用 `launch_task` + `wait_for_tasks`（解耦 `train_backend.py` 重构，本 PR 不动）
- **前端 TaskPanel**：UI 显示 task lifecycle + 心跳进度（目前 heartbeat 事件已发，但前端无专门 panel 渲染）
