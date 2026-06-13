# Current Task

**当前任务**: NAS workflow 鲁棒性测试 —— 多输入契约测试项目已建，下一步跑 NAS 验证
**状态**: 3 个新测试项目（multi_input / list_input / dict_input）建好 + 独立训练/eval 跑通；下一步用 NAS workflow 实测
**日期**: 2026-06-13
**分支**: `main`（上次 commit `479baaa`）

## 必读文件

- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/nas-workflow-requirements.md` — NAS 架构决策
- `workflows/nas/helpers/` — 10 个 helper（含新 onnx + chart）
- `workflows/nas/agents/` — 9 个 agent MD（已加 onnx 步骤 + render_charts 调用）
- `projects/` — 4 个测试项目，覆盖 4 种 forward 签名

## 测试项目矩阵（输入契约压力测试）

| 项目 | forward 签名 | 数据 | baseline acc | params |
|------|-------------|------|--------------|--------|
| `mnist` | `model(x)` 单 tensor `(B, 64)` | sklearn digits | ~0.95 | ~5K |
| `multi_input` | `model(x_a, x_b)` 两 tensor 各 `(B, 32)` | digits 拆 32+32 | ~0.94 | ~14K |
| `list_input` | `model(x_list)` List[Tensor] × 3，各 `(B, 16)` | 合成 3 通道信号检测 | 1.0 | ~6K |
| `dict_input` | `model({"user": u, "item": i})` dict | 合成 prototype 推荐 | 1.0 | ~10K |

每个项目都有独立的 `model.py` / `train.py` / `eval.py` / `README.md`，独立可跑，秒级训练。

## 已落地（待 commit）

### ONNX 评测链路（之前轮的工作）
- `helpers/export_onnx.py` / `measure_onnx_latency.py` / `fitness.py --use-onnx-latency`
- scout/trainer/refiner/judger agents 加 ONNX 步骤
- smoke test 通过；端到端跑测待验证

### Result 标签可视化
- `helpers/render_charts.py`：scatter / optimal_line / line / table / bar 5 类图 × N tier × 2 latency source
- analyzer / reporter agents 加 render_charts 调用

### 测试项目（本轮新增）
- ✅ `projects/multi_input/`：`model(x_a, x_b)`，digits 拆半，两分支融合（concat/sum/mul）
- ✅ `projects/list_input/`：`model(x_list)`，3-channel 合成信号检测，4 种聚合（默认 concat）
  - **坑**：mean/max/sum 聚合在"哪个 channel 有信号"任务上不收敛（信息被 pool 掉）；默认改 concat
- ✅ `projects/dict_input/`：`model({"user", "item"})`，prototype-based 推荐，4 种融合
  - **坑**：dot-product bucketing 任务对两塔太难（acc 卡随机 0.33）；换 prototype-based 后立刻 1.0

## 待办

- [ ] **P0 跑 NAS workflow 验证 4 个项目都能跑通** —— 重点测：
  - workflow 是否能识别非单 tensor forward 签名（multi_input 的 `model(x_a, x_b)`、list_input 的 `model(x_list)`、dict_input 的 `model(dict)`）
  - export_onnx.py 默认 `--input-shape 1,64` 在这些项目上失败时 workflow 怎么处理（**预期会暴露 workflow 的契约假设**）
  - 前端 result 标签图表显示
- [ ] **commit**：测试项目 + 之前 ONNX/chart 改动一起 commit
- [ ] **trainer sub_agent 写 cwd 问题**（独立架构问题）
- [ ] **MCP cleanup bug**

## 旁路任务

- AppView 重构代码完成，等用户浏览器手测验收（5 场景）→ 见 `docs/releases/2026-06-12-appview-hydration-refactor.md`

