# 2026-06-26 — claude-code 路径盘驱动 + 工具映射 + env 配置修复

## Context

用户在前端 DAG 节点上切换 executor 为 `claude-code`（PATCH 成功写盘），但启动 run 后实际走的是 `pydantic-ai` 路径。逐步定位后发现这不是单点 bug，而是 **4 层独立的契约错位 / 配置缺口叠加**。本 release 收尾前 3 层修复 + agent MD 加载缺口；ask_user 实际调用链路与 Phase G 翻译器补全仍未解决。

## 4 层根因

| 层 | 现象 | 根因 |
|---|---|---|
| 1 | 切了 executor 仍跑 pydantic-ai | `_create_and_start_workflow` 用 POST body 的 agents 字段**覆盖** disk workflow.json，前端 `useWorkflowLaunch` 漏传 executor 导致默认值覆盖盘上的 claude-code |
| 2 | claude spawn 后 182ms exit 1 stderr 空 | `_resolve_allowed_tools` 把 harness 工具名 `ask_user` 直接传给 claude `--allowed-tools`，claude 拒识（期望 `mcp__harness__ask_user`） |
| 3 | exit 1 stderr 空，跑了 183s 才失败 | bigmodel.cn (LLM gateway) 529 限流，claude retry 10 次后放弃 |
| 4 | 换 DeepSeek 后还是 400 模型不存在 | `~/.claude/settings.json` 的 `env` 字段（bigmodel.cn）优先级高于 shell env，覆盖了项目 .env 的 DeepSeek 配置 |
| 5 | DeepSeek 跑通后 greeter 没调 ask_user 反而读 CURRENT.md | `node_factory` 构造 deps 时没填 `agent_md_content`，`ClaudeCodeExecutor._resolve_system_prompt` 拿不到 MD 指令 |

## 改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `server/_helpers.py:42-92` | `_validate_workflow_dir` 查找顺序改为 shared → private → legacy → registry（与 `list_saved_workflows` 一致，避免 PATCH 写一处 POST 读另一处的契约错位） |
| `server/_helpers.py:237-295` | `_create_and_start_workflow` 改为盘驱动：workflow.json 存在时完全用盘上 agents 定义，POST body 仅作 ad-hoc fallback；移除"POST 覆盖 disk baseline"逻辑 |
| `server/_helpers.py:561-576` | `_reconstruct_run_to_repo` 加 `executor=a.get("executor")`（resume 路径不再丢字段） |
| `server/schemas.py:26-33, 153-159` | `CreateWorkflowRequest.agents` / `CreateBatchRequest.agents` 改为 `Optional`（ad-hoc only） |
| `server/runner.py:62-80` | `_build_agents_snapshot` 非默认 executor 写入 snapshot（与 `Agent.to_dict` 行为一致） |
| `harness/core/workflow_persist.py:141-147` | `list_saved_workflows` legacy glob 加 dedupe（避免同名 entry 双发，前端 Map 后写入胜出 = legacy 老副本） |
| `harness/engine/claude_code_executor.py:404-435` | `_resolve_allowed_tools` 加映射规则：小写起头的 harness 工具名自动加 `mcp__harness__` 前缀；大写起头（claude 内置）/ 已 mcp__ 前缀的原样透传 |
| `harness/engine/claude_code_executor.py:278-360` | `_build_spawn_config` 加 `_load_env_overlay`：读项目 `.env` 的 `ANTHROPIC_*`/`CLAUDE_*` 作为子进程 env overlay，覆盖父进程 env |
| `harness/engine/_claude_subprocess.py:25-35` | `DEFAULT_FLAGS` 加 `--setting-sources project`：跳过 `~/.claude/settings.json` 的 env 字段（否则其优先级高于 shell env，会覆盖项目 .env 配置） |
| `harness/engine/node_factory.py:218-228` | 构造 `AgentDeps` 时加 `agent_md_content=augmented_prompt`（`AgentDeps` `extra="allow"` 允许动态字段），让 ClaudeCodeExecutor 拿到 agent MD 作为 `--append-system-prompt` |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/hooks/useWorkflowLaunch.ts:30-36` | scoped 入口移除 POST body 的 agents 字段（盘驱动后不需要） |

### 数据

| 文件 | 改动 |
|---|---|
| `.env` | 加 DeepSeek 的 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` 等（调试阶段全用 `deepseek-v4-flash`，不用 pro） |
| `workflows/ask_user_demo/`（legacy 副本） | 删除（与 shared 副本同名导致 dedupe 前双发，已删避免混乱） |

### 测试

| 文件 | 改动 |
|---|---|
| `tests/server/test_create_workflow_disk_driven.py` | 新增 6 测试：盘存在用盘 / POST 不覆盖盘 / ad-hoc fallback / ad-hoc 无 agents fail loud / snapshot 写 executor / reconstruct 保 executor |

## 测试覆盖

- Python fast 单测：39（含 6 新增）全绿
- 手动验证：手动跑 claude CLI（用同样 env + cmd）确认 DeepSeek 调通（输入 26756 tokens，输出 62 tokens，cost $0.135）

## 设计原则确立

**workflow.json 是 agents 定义的唯一真相源**：
- PATCH 写盘是唯一权威写入路径
- GET /workflows/definitions 返回完整 agent 定义（含 executor）
- POST /api/workflows 启动 run 时，agents 定义完全从盘读，POST body 仅 ad-hoc fallback
- 3 个调用方（create_workflow / create_batch / run_benchmark）共享同一 `_create_and_start_workflow`，改一处全受益

## 未解决（标注清楚）

### ask_user 实际调用链路未验证

`agent_md_content` 修复（node_factory.py）后，理论上 claude 会拿到 greeter.md 指令并调 `mcp__harness__ask_user`。但**端到端实测未做**（用户改 .env + 重启 server 后没再启动 run 验证）。需要：
1. 启动 ask_user_demo run
2. 看 events 是否出现 `agent.tool_call: tool_name=mcp__harness__ask_user`
3. 前端是否弹出问题卡片
4. 用户选答案后 ask_user handler 是否 resolve

### Phase G 翻译器补全（CURRENT.md 既列已交付，实为部分）

| 子项 | 真实状态 |
|---|---|
| G1 token/cost | ✅ |
| G3 SIGTERM | ✅ |
| G4 thinking_delta | ✅ |
| G5 并发 ask_user | 未验证（依赖 ask_user 链路） |
| G6 防御性解析 | ✅ |
| G2 bash 实时流 | ❌ claude CLI 2.1.150 stream-json 协议限制 |
| G7 冷启动优化 | ❌ 等 claude CLI 升级 |

**翻译器覆盖度（实际）**：

| stream-json 事件 | 翻译状态 | 前端可见性 |
|---|---|---|
| `system/init` | ✅ → `node.started` | ✅ |
| `assistant` + text/thinking | ✅ → `agent.text_delta` / `thinking_delta` | ✅ |
| `result` (success) | ✅ → `node.completed` | ✅ |
| `result` (is_error=true) | ⚠️ 翻成 text_delta，未标 error | 看到文本但不知是错误 |
| `system/api_retry` | ❌ 未翻译 | 看不到 retry 状态（"卡住"感来源） |
| `system/status` (requesting/thinking) | ❌ 未翻译 | 看不到 LLM 调用阶段 |

**前端展示 gap**：即便后端 emit 了 `workflow.error`，前端 UI 设计成"等很久才弹一行错误"，没有"实时显示 retry 次数 / 错误演进"的 UI。

## 后续工作（不在本 release）

1. **ask_user 端到端验证**：补 e2e 测试 + 实测确认 `mcp__harness__ask_user` 调用链路
2. **翻译器补全**：`api_retry` / `status` / `result.is_error` 映射到 harness event
3. **前端 retry UI**：实时显示 retry 次数 / LLM 调用阶段
4. **可扩展执行器架构**：抽象 `CliSpawnExecutor` 基类，未来加 opencode 等工具只需加子类 + 配置文件
5. **前端可配置 LLM**：让用户在前端修改 ANTHROPIC_* / HARNESS_* 配置（目前只能改 .env）
