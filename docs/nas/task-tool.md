# Task 工具 — 后台任务生命周期管理

> 状态：待实现
> 对比参考：Claude Code Agent + TaskOutput + TaskStop

## 设计目标

管理**后台长时间运行的任务**：sub-agent 执行、训练进程、评测脚本。
需要创建、查询、停止，并追踪状态（运行中/成功/失败）。

与 TODO 工具的关系：
- **TODO** = agent 的规划清单（"我要做哪几步"），轻量、同步
- **Task** = 后台进程管理（"这些训练在跑"），重量、异步
- 一个 TODO step 可能 spawn 多个 Task（如"并行执行策略" → N 个训练 task）

---

## 工具接口（草案）

```python
task(
    op: Literal["spawn", "output", "stop", "list"],

    # spawn
    command: str | None = None,           # bash 命令
    agent_task: str | None = None,        # sub-agent 任务描述
    workdir: str | None = None,           # 隔离工作目录（worktree 路径）
    metadata: dict | None = None,

    # output
    task_id: str | None = None,
    block: bool = True,
    timeout: int = 30000,

    # stop
    task_id: str | None = None,
) -> str
```

### 操作行为

| op | 行为 |
|----|------|
| `spawn` | 启动后台任务（sub-agent 或子进程），返回 `task_id` |
| `output` | 获取任务输出，`block=True` 等待完成 |
| `stop` | 终止任务 |
| `list` | 列出所有任务及状态 |

---

## TaskManager（内部）

```python
class TaskManager:
    """进程级单例，管理所有后台任务"""

    async def spawn(self, command=None, agent_task=None, workdir=None) -> str:
        task_id = f"t_{uuid4().hex[:8]}"
        if command:
            proc = asyncio.create_subprocess_exec(..., cwd=workdir)
            self._tasks[task_id] = ProcessTask(task_id, proc)
        elif agent_task:
            self._tasks[task_id] = AgentTask(task_id, agent_task, workdir)
        self.event_bus.emit("task.spawned", {...})
        return task_id

    async def output(self, task_id, block, timeout) -> TaskResult: ...
    async def stop(self, task_id) -> None: ...
```

---

## 事件协议（草案）

```json
// task.spawned
{"type": "task.spawned", "payload": {"task_id": "t_abc", "command": "python train.py", "workdir": "/tmp/wt1"}}

// task.status (周期性)
{"type": "task.status", "payload": {"task_id": "t_abc", "status": "running", "stdout_tail": "..."}}

// task.completed
{"type": "task.completed", "payload": {"task_id": "t_abc", "exit_code": 0, "duration": 3600}}

// task.failed
{"type": "task.failed", "payload": {"task_id": "t_abc", "error": "OOM"}}
```

---

## 与现有 SubAgentToolFactory 的关系

当前 `SubAgentToolFactory` 实现 sub-agent 逻辑。建议**统一归 Task 管**：
- `task(op="spawn", agent_task="...")` 替代 `sub_agent` 工具
- `task(op="spawn", command="python train.py")` 管理子进程
- 前端只有一个任务面板
- agent 用 `task(op="output", block=true)` 统一等待结果

迁移策略：
1. 先实现 Task 工具
2. SubAgentToolFactory 内部改调 TaskManager
3. 保留 `sub_agent` 工具作为薄壳（向后兼容）
4. 后续版本移除 `sub_agent`

---

## 前端渲染（草案）

新增 `taskStore` + Task 面板组件：

```
┌─ TASKS ──────────────────────────────┐
│ 🔵 t_abc  python train.py     2m 30s │ ← running + pulse
│    stdout: Epoch 45/100, loss=0.32... │
│                                      │
│ ✅ t_def  python eval.py      1m 12s │ ← completed
│    exit_code: 0, accuracy: 0.892     │
│                                      │
│ 🔴 t_ghi  python train.py     0m 45s │ ← failed
│    Error: CUDA out of memory         │
└──────────────────────────────────────┘
```

---

## 评估

| 维度 | 评估 |
|------|------|
| 开发量 | ~5 天（TaskManager + sub-agent 调度 + 进程管理 + 4 个事件 + 前端） |
| 风险 | 中（进程管理是主要风险点：OOM、超时、断连恢复） |
| 前置依赖 | 代码隔离方案（git worktree）需先确定 |
| 可扩展性 | 高（metadata 字段可扩展，后续可加 GPU 资源限制、优先级） |
