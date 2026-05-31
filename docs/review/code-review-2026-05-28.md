# AgentHarness 项目全面审查报告

**日期**: 2026-05-28
**审查范围**: 全项目（Python 后端 + TypeScript 前端 + 架构设计）

---

## 项目规模

- Python 后端：~17,800 行（53 个文件）
- TypeScript 前端：~15,200 行
- 测试：249 个用例（13 个被标记 slow）

---

## 一、代码质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 类型标注 | 7/10 | Pydantic BaseModel 好，但存在 `Any` 滥用 |
| 错误处理 | 6/10 | 自定义异常好，但 `except Exception` 泛捕获过多 |
| 测试覆盖 | 6/10 | 编译器和工具测试好，macro_graph 和集成测试不足 |
| 命名一致性 | 7/10 | 总体清晰，少量中英文混用 |
| 文档 | 8/10 | CLAUDE.md、SPEC.md 文档体系完善 |

---

## 二、违反的设计原则

### 1. 单一职责原则 (SRP) — 严重违反

- `macro_graph.py`（996 行）：同时负责 DAG 编译、节点创建、中断恢复、EvalJudge 集成、stop-and-regenerate。建议拆分为 `GraphBuilder`、`NodeFactory`、`InterruptManager`
- `api.py`（848 行）：Workflow 类同时处理编排、持久化、UI 启动、MCP 设置
- `routes.py`（1514 行）：最大的单文件，涵盖所有 REST 端点 + Pydantic schema 定义 + 业务逻辑

### 2. 依赖倒置原则 (DIP) — 部分违反

- LLM 客户端紧耦合 OpenAI provider，没有 provider 抽象层
- 直接文件 I/O 混在业务逻辑中（`run_store.py`、`benchmark_store.py`），没有 repository 接口
- 大量全局单例（`ResourceRegistry`、`Bus`、`UserManager`、`CheckpointManager`）代替了依赖注入

### 3. 接口隔离原则 (ISP) — 轻微违反

- `ToolFactory` 接口干净，但 `BaseMiddleware` 的 `before_node`/`after_node`/`before_tool` 没有拆分——一个中间件可能只关心其中一个却被迫实现全部（虽然是 no-op 默认）

### 4. 开闭原则 (OCP) — 扩展系统做得好

- Hook/Middleware/GraphMutator 三级扩展契约设计优秀
- `ToolFactory` 注册表机制良好
- 但 Workflow 类的 `compile()` 方法内有硬编码的 mutator 调用逻辑

---

## 三、架构亮点

1. **双引擎设计（LangGraph macro + Pydantic AI micro）** — 职责边界清晰，macro 负责 DAG 编排，micro 负责单节点执行
2. **三级扩展系统** — Hook（观测）/ Middleware（改写）/ GraphMutator（结构变更）映射到不同扩展意图，隔离性好
3. **EventBus + WebSocket 实时流** — pub/sub 解耦前后端，支持 streaming、chart、human-in-the-loop
4. **声明式 Workflow API** — `Agent` + `Workflow` 的声明式定义简洁易用
5. **资源注册表（ResourceRegistry）** — 两层发现（project + builtin）设计合理

---

## 四、已实现的扩展 vs 计划中

| 扩展 | 状态 | 接口就绪 |
|------|------|----------|
| AutoCompact | ✅ 已实现 | ✅ |
| EvalJudge | ✅ 已实现 | ✅ |
| Plugin hooks（4 个） | ✅ 已实现 | ✅ |
| ApprovalGate | 🚧 仅 SPEC | ✅ 契约已定义 |
| TokenBudget | 🚧 仅 SPEC | ❌ 需 SkipAction |
| PromptCache | 🚧 仅 SPEC | ❌ 需 MessageView |
| Guardrail | 🚧 仅 SPEC | ✅ RejectAction 可用 |
| Memory | 🚧 仅 SPEC | ❌ 需持久化抽象 |
| Tracing | 🚧 仅 SPEC | ✅ Hook 契约可承载 |

---

## 五、未考虑的关键点

### 1. 持久化层抽象缺失
- `RunStore`、`BenchmarkStore` 直接操作文件系统（JSON 文件）
- 没有统一的 repository 接口，无法切换到数据库
- 多实例部署时数据不共享，无法水平扩展

### 2. 多进程/多节点支持
- `WorkflowRepository` 明确标注"非线程安全"，设计为单进程
- Bus 是进程级单例，跨进程事件需要额外中间件
- Semaphore 并发控制在单进程内有效，无法跨节点协调

### 3. 安全边界不足
- Bash 工具执行 shell 命令，`work_dir` 是唯一的沙箱边界
- 没有命令白名单/黑名单机制
- MCP server 进程管理缺少资源限制（内存、CPU）
- API 认证仅依赖 `X-User-Id` header，无 JWT/OAuth

### 4. 可观测性缺口
- 没有结构化日志（structured logging）
- 没有 OpenTelemetry 集成
- 错误追踪依赖 `ext.error` 事件，无外部告警
- 没有 Prometheus metrics 端点

### 5. 前端状态一致性
- 多个 Zustand store 被同一 WebSocket 事件并行更新
- 没有 transaction 语义，可能出现中间状态闪烁
- 长时间 batch 运行可能导致内存增长（per-workflow cache 累积）

### 6. 错误恢复与容错
- Checkpoint/Resume 功能存在但测试覆盖不足
- 工作流执行失败后的部分结果处理策略不明确
- 没有死信队列（dead letter queue）用于失败事件
- LLM API 调用的退避重试策略不够精细（仅简单重试）

### 7. 资源生命周期管理
- MCP server 进程依赖 `try/finally` 清理，异常路径可能泄漏
- 长时间运行的 workflow 可能积累大量未清理的状态
- WebSocket 断连后的状态恢复依赖 event buffer（上限 2000），超限事件丢失

### 8. 版本与兼容性
- Workflow JSON schema 没有版本号，无法做向后兼容迁移
- Agent MD frontmatter 格式变更没有迁移路径
- API 端点没有版本前缀（`/api/v1/`）

### 9. 测试策略缺口
- 没有 E2E 测试（需要 LLM 调用的全链路验证）
- macro_graph 的单元测试不足（996 行只有 llm_executor 被单独测试）
- 没有 chaos/resilience 测试（网络中断、LLM 超时、进程崩溃）
- 前端完全没有测试

### 10. 性能考虑
- 没有基准性能测试（大 DAG、高并发 workflow 的吞吐量）
- Event buffer 使用 `deque(maxlen=2000)`，高吞吐场景可能丢事件
- 前端没有虚拟列表（大量消息时的渲染性能）

---

## 六、优先改进建议

| 优先级 | 改进项 | 原因 |
|--------|--------|------|
| P0 | 拆分 `macro_graph.py` | 996 行 god file，是扩展系统的核心瓶颈 |
| P0 | 拆分 `routes.py` | 1514 行，schema 定义应独立，路由按领域分组 |
| P1 | 添加 workflow schema 版本号 | 无版本号意味着无法安全演进 |
| P1 | 补充 macro_graph 单元测试 | 核心路径覆盖不足 |
| P1 | 前端关键路径 E2E 测试 | 目前前端零测试 |
| P2 | 统一持久化接口 | 为未来数据库支持铺路 |
| P2 | 结构化日志 + metrics | 生产环境必需 |
| P2 | API 版本前缀 | `/api/v1/` |
| P3 | Provider 抽象层 | 解耦 LLM 供应商 |
| P3 | 前端虚拟列表 | 大规模使用时的性能保障 |

---

## 总结

项目核心架构设计扎实——双引擎 + 三级扩展 + EventBus 的组合在同类框架中有独到之处。**扩展系统的接口设计是最大亮点**，ToolFactory / BaseHook / BaseMiddleware / BaseGraphMutator 契约清晰、隔离性好、易扩展。

主要风险集中在两个方面：**代码组织的 SRP 违反**（三个超长文件）和**生产就绪性的缺口**（持久化抽象、安全边界、可观测性）。这些在 PoC 阶段可以接受，但如果目标是生产使用，需要按优先级逐步补齐。
