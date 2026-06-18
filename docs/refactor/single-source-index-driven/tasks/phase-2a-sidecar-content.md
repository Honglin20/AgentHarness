# Phase 2a: sidecar 加 tool_calls + todo_steps

> **目标**：D2 + O1 决策落地。sidecar 内容完整化，让历史 iter 看到完整 tool 历史 + todo。
> **ADR 依据**：D2 / O1
> **预估**：0.5 天，7 个任务
> **用户感知**：点 scout iter 1 → 看到 iter 1 的完整 tool_calls + todo（之前只有 output）。

## 任务清单

---

### P2a-T01: `_save_incremental` 写 sidecar 时加 `tool_calls` 字段

**Phase**: P2a
**预估**: ~10 分钟
**依赖**: P0 完成
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
sidecar 写盘时把 agent_io[node].tool_calls 也写进去，让历史 iter 能看到完整工具调用历史。

#### 代码计划
- **`harness/engine/incremental_save.py`** (修改)
  - line 113-125 的 `iter_data` 字典加：
    ```python
    "tool_calls": node_io.get("tool_calls", []) if isinstance(node_io, dict) else [],
    ```
  - 每个 tool_call 应包含：tool_name, tool_args, tool_result（已有）

#### 产出标准
- [ ] 新 sidecar 文件含 tool_calls 字段（数组）
- [ ] tool_calls 内容和 agent_io[node].tool_calls 一致

#### 验证方法
```bash
# 手动跑一次 incremental_save（mock 或真跑），检查新 sidecar
python3 -c "
import json
# 假设新跑了一个 run，sidecar 在 runs/<new_run_id>+iters+scout+1.json
# 验证字段存在
p = 'runs/<new_run_id>+iters+scout+1.json'
data = json.load(open(p))
print('tool_calls count:', len(data.get('tool_calls', [])))
"
# 预期：>= 0（ NAS scout 通常 10+ tool calls）
```

#### 代码质量检查
- [ ] 单一职责：只加字段，不动其他逻辑
- [ ] Fail loud：node_io 不是 dict 时返回空 list（defensive）
- [ ] 无 magic：tool_calls 字段名和 schema 一致

#### Review 检查
- [ ] DoD 满足
- [ ] tool_calls 内容完整（含 result）

---

### P2a-T02: `_save_incremental` 写 sidecar 时加 `todo_steps`（按 iter 过滤）

**Phase**: P2a
**预估**: ~15 分钟
**依赖**: P2a-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
O1 决策：todo_steps 从 snapshot 迁出，按 iter 过滤后写入对应 sidecar。

#### 代码计划
- **`harness/engine/incremental_save.py`** (修改)
  - line 113-125 的 `iter_data` 字典加：
    ```python
    node_todo = builder.todo_states.get(node_id, []) or []
    "todo_steps": [s for s in node_todo if isinstance(s, dict) and s.get("iteration") == iter_num],
    ```
  - 注：todo step 已经带 iteration 字段（见 ADR O1 实测）

#### 产出标准
- [ ] 新 sidecar 含 todo_steps 字段
- [ ] todo_steps 只包含本 iter 的 steps（不是全部）
- [ ] 缺 iteration 字段的 step 不被包含（defensive）

#### 验证方法
```bash
python3 -c "
import json
p = 'runs/<new_run_id>+iters+scout+1.json'
data = json.load(open(p))
todos = data.get('todo_steps', [])
print('todo count:', len(todos))
print('all iter=1?:', all(s.get('iteration') == 1 for s in todos))
"
```

#### 代码质量检查
- [ ] 单一职责
- [ ] Fail loud：todo step 没 iteration 字段时跳过（log warning？或静默——见 review）
- [ ] 按 iter 过滤逻辑清晰

#### Review 检查
- [ ] DoD 满足
- [ ] 缺 iteration 字段的处理方式（静默跳过 vs log）是否合理

---

### P2a-T03: `_iter_sidecar_to_messages` 投影 tool_calls 为 ConversationMessage

**Phase**: P2a
**预估**: ~15 分钟
**依赖**: P2a-T01
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
sidecar API 端点的投影函数加 tool_calls → ConversationMessage 的转换。

#### 代码计划
- **`server/routers/runs.py`** (修改)
  - `_iter_sidecar_to_messages(sidecar, node_id, iter_num)`：
    - output / input_prompt 投影保留
    - 新增 tool_calls 投影：
      ```python
      for tc in sidecar.get("tool_calls", []):
          out.append({
              "id": _next_id(),
              "type": "tool_call",
              "nodeId": node_id,
              "agentName": node_id,
              "content": "",
              "toolName": tc.get("tool_name", ""),
              "toolArgs": tc.get("tool_args", {}),
              "toolResult": str(tc.get("tool_result")) if tc.get("tool_result") is not None else None,
              "toolStatus": "done",
              "timestamp": tc.get("ts", 0),
              "iteration": iter_num,
          })
      ```

#### 产出标准
- [ ] API 返回的 messages 含 tool_call 类型条目
- [ ] tool_call 字段映射正确（toolName/toolArgs/toolResult）
- [ ] 顺序：tool_calls 在 output 之后（或按 ts 排序）

#### 验证方法
```bash
# 启动 server，curl 测端点
curl 'http://localhost:8000/api/runs/<run_id>/nodes/scout/iters/1' | python3 -m json.tool | head -30
# 预期：包含 tool_call 类型的 messages
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 一致性：字段名和 frontend ConversationMessage 类型对齐
- [ ] 边界：tool_result 是 None 时不抛

#### Review 检查
- [ ] DoD 满足
- [ ] 字段映射和 build_conversation 的 tool_call 格式一致

---

### P2a-T04: `_iter_sidecar_to_messages` 投影 todo_steps

**Phase**: P2a
**预估**: ~10 分钟
**依赖**: P2a-T02
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
todo_steps 在 sidecar API 响应中暴露（作为 sidecar 字段，不是 messages）。前端从 sidecar 拿 todo。

#### 代码计划
- **`server/routers/runs.py`** (修改)
  - `get_node_iter_detail` 端点：当前直接返回 sidecar dict，已包含 todo_steps（P2a-T02 写入的）。
  - 无需改动 endpoint 本身，但确认前端 hydration 能消费。

#### 产出标准
- [ ] API 响应含 todo_steps 字段
- [ ] 前端能从 sidecar 读 todo_steps 渲染（验证 P2a-T07）

#### 验证方法
```bash
curl 'http://localhost:8000/api/runs/<run_id>/nodes/scout/iters/1' | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('todo_steps count:', len(data.get('todo_steps', [])))
"
```

#### 代码质量检查
- [ ] 单一职责
- [ ] 一致性：字段名和 schema 一致

#### Review 检查
- [ ] DoD 满足
- [ ] 前端能消费（依赖 P2a-T07 验证）

---

### P2a-T05: 单测：tool_calls 写盘 + 投影

**Phase**: P2a
**预估**: ~10 分钟
**依赖**: P2a-T01, P2a-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
覆盖 tool_calls 写盘和投影逻辑。

#### 代码计划
- **`harness/engine/test_incremental_save.py`** 或新增 `test_iter_sidecar.py` (修改/新增)
  - 测试：mock 一个 agent_io 含 tool_calls，调 _save_incremental，验证 sidecar 文件含 tool_calls
  - 测试：调 _iter_sidecar_to_messages，验证输出含 tool_call 类型 messages
  - 测试：tool_result 是 None 时投影不抛

#### 产出标准
- [ ] 3 个测试用例全过

#### 验证方法
```bash
python3 -m pytest harness/engine/test_incremental_save.py -v -k tool_calls 2>&1 | tail -10
# 预期：3 passed
```

#### 代码质量检查
- [ ] 测试意图清晰
- [ ] mock 严格

#### Review 检查
- [ ] DoD 满足

---

### P2a-T06: 单测：todo_steps 按 iter 过滤

**Phase**: P2a
**预估**: ~10 分钟
**依赖**: P2a-T02
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
验证 todo_steps 按 iter 过滤逻辑。

#### 代码计划
- **`harness/engine/test_incremental_save.py`** (修改)
  - 测试：node 有 5 个 steps（3 个 iter=1, 2 个 iter=2），写 iter=1 sidecar → todo_steps 含 3 个
  - 测试：node 没 todo_steps 时，sidecar 中 todo_steps=[]（不抛）
  - 测试：step 缺 iteration 字段时不被包含

#### 产出标准
- [ ] 3 个测试用例全过

#### 验证方法
```bash
python3 -m pytest harness/engine/test_incremental_save.py -v -k todo 2>&1 | tail -10
```

#### 代码质量检查
- [ ] 测试意图清晰

#### Review 检查
- [ ] DoD 满足

---

### P2a-T07: 真机验证：旧 run 历史 iter 看到 tool_calls

**Phase**: P2a
**预估**: ~10 分钟
**依赖**: P2a-T01, P2a-T02, P2a-T03
**状态**: ✅ 已完成 (2026-06-17)

#### 功能点
跑一个新的 NAS run（或重启增量保存让现有 run 的 sidecar 被刷新），真机验证：
- 切到 scout 历史 iter → 看到 tool_calls
- AgentDetailView 渲染 todo

#### 代码计划
- 无代码改动，纯验证
- 跑 NAS workflow（缩短到 1-2 iter），刷新页面，逐个 iter 点击验证

#### 产出标准
- [ ] scout iter 1 显示 tool_calls（10+ 条）
- [ ] scout iter 1 显示 todo steps
- [ ] 切到 iter 2 内容替换（不残留 iter 1）

#### 验证方法
```bash
# 启动 server
python3 -m uvicorn server.app:app --reload &
# 启动 frontend
cd frontend && npm run dev &
# 浏览器访问 http://localhost:3000，跑 NAS workflow
# 手动验证：
# 1. outline 显示 scout 有 N 个 iter
# 2. 点 scout → 默认显示最新 iter，有 tool_calls
# 3. 切到 iter 1 → 看到 iter 1 的 tool_calls（不是最新的）
```

#### 代码质量检查
- [ ] 真机验证清单完整
- [ ] 截图 / 录屏作为 evidence（可选）

#### Review 检查
- [ ] DoD 满足
- [ ] 用户确认能看到历史 iter 完整内容

---

## Phase 2a 完成标准

- [ ] 所有 7 个任务 ✅
- [ ] sidecar schema 含 tool_calls + todo_steps
- [ ] API 端点投影 tool_calls 到 messages
- [ ] 真机验证历史 iter 内容完整
- [ ] Release note：`docs/releases/2026-06-xx-phase-2a-sidecar-content.md`
