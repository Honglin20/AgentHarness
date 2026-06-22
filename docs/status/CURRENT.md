# Current Task

**当前任务**: (无活跃任务 — 长耗时任务 MVP 已完成，等用户决定 Phase 2 / NAS 接入)

## 上一任务: Workflow Agent 长耗时后台任务支持（2026-06-22）

补齐 harness 缺失的关键原语——agent 启动长耗时后台任务（DL 训练）后能阻塞等待完成。新增 `launch_task` + `wait_for_tasks` 等 4 个工具，**两个 `timeout_ms` 默认都是 0**（永不杀进程 / 无限等）。

详见 [`docs/releases/2026-06-22-long-running-task-support.md`](../releases/2026-06-22-long-running-task-support.md)。

---

## 待办（待用户确认才动）

### Phase 2 — 长耗时任务跨 session 恢复（触发条件待定）
- 持久化 registry：`runs/{run_id}/tasks/{task_id}.json`（write-through）
- Detached 本地执行：`os.setsid()` + reaper 线程下次 CLI 启动 re-attach
- `SSHBackend.launch()` 用 Popen + 远程 `EXIT_CODE` 轮询
- `dispatch_train(mode="launch")` 给 adapter 侧异步路径
- **触发条件**：训练 >24h / 需切换设备 / 远端训练

### Phase 3 — Cloud + UI 增强
- `CloudBackend.launch` 走 `autodl_api.wait_running` 轮询模式
- 前端 TaskPanel：渲染 task lifecycle + 心跳进度（目前 heartbeat 事件已发但无专门 UI）
- 可选 `on_task_complete` 条件边（fan-out 驱动路由场景）

### NAS workflow 接入
- `workflows/nas/agents/baseline_runner.md` 等训练相关 agent prompt 更新，改用 `launch_task` + `wait_for_tasks`
- 与 `train_backend.py` 重构解耦，本 PR 不动 NAS

### 历史（Q1/Q2/Q3）
- Q1 Token 计数显示修复已完成（2026-06-21）
- Q2 Claude Code prompt 补齐 — 未启动
- Q3 Prompt 统一管理重构 — 未启动

## 必读文件

- `harness/tools/task_registry.py` — TaskRecord + TaskRegistry（per-workflow singleton）
- `harness/tools/launch_task.py` — launch_task 工具（含 on_complete 回调注入）
- `harness/tools/task_wait.py` — wait_for_tasks / list_tasks / cancel_task 工具
- `harness/tools/bash.py:360-470` — spawn_background 加 `on_complete` 参数
- `harness/extensions/bus.py:83-105` — task.* 加入 CRITICAL_EVENT_TYPES（heartbeat 故意不加）
- `workflows/long_task_demo/` — 完整 demo workflow（mock_train.py + train_and_eval.md）
