# Current Task

**当前任务**: NAS workflow ONNX 导出全输入契约支持 —— 已实现，下次跑 NAS 实测
**状态**: export_onnx + measure_onnx_latency 重构完，4 个测试项目（tensor/tuple/list/dict）全部跑通；agent MD 更新到位
**日期**: 2026-06-13
**分支**: `main`（上次 commit `29cb8c1`）

## 必读文件

- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/nas-workflow-requirements.md` — NAS 架构决策
- `workflows/nas/helpers/export_onnx.py` — 自动探测 forward 签号
- `workflows/nas/helpers/measure_onnx_latency.py` — 按 onnx input_names 反推 feeds
- `projects/` — 4 个测试项目，覆盖 4 种 forward 签名

## 输入契约支持矩阵（已 E2E 验证）

| 项目 | forward 签名 | dummy_inputs 返回 | export | measure latency |
|------|-------------|-------------------|--------|-----------------|
| `mnist` | `model(x)` | Tensor | ✅ 0.018ms | ✅ |
| `multi_input` | `model(x_a, x_b)` | Tuple[Tensor, Tensor] | ✅ 0.025ms | ✅ |
| `list_input` | `model(x_list)` | List[Tensor] × 3 | ✅ 0.033ms (wrapper) | ✅ |
| `dict_input` | `model({"user","item"})` | Dict[str, Tensor] | ✅ 0.024ms (wrapper) | ✅ |

## 已落地（本轮，待 commit）

### export_onnx.py 重构
- 自动扫 `nn.Module` 子类（MODEL_CLASS 优先 → 单类 → 命名启发式 → 最后定义）
- 自动调 `model.dummy_inputs(batch_size=1)` 推导输入契约
- Tensor / Tuple → 直接 positional；List / Dict → wrapper 展开
- 缺 dummy_inputs → fallback 单 tensor + stderr warning

### measure_onnx_latency.py 重构
- 从 onnx session 读 input_names，按 dummy_inputs 重映射成 feeds
- 支持 tensor / tuple / list / dict 全部 4 种
- 缺 dummy_inputs + 多输入 → fail loud 提示

### 4 个项目 model.py 加 dummy_inputs 函数

### Agent MD 更新
- `scout.md` domain_analyzer：探测 forward 签名 + 自动补 dummy_inputs 函数
- `scout.md` baseline_runner / `trainer.md` / `refiner.md`：export 失败 → 读 forward 签名补 dummy_inputs 重试

## 待办

- [ ] **P0 跑 NAS workflow 实测 4 个项目** —— 验证 agent 能正确调 helper
- [ ] **commit** 当前改动
- [ ] **trainer sub_agent 写 cwd 问题**（独立架构问题）
- [ ] **MCP cleanup bug**

## 旁路任务

- AppView 重构代码完成，等用户浏览器手测验收（5 场景）→ 见 `docs/releases/2026-06-12-appview-hydration-refactor.md`


