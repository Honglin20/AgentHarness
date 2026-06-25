# Plan: NAS + AutoDL 云端训练（ASI 验证）

**Date**: 2026-06-19
**Goal**: 用真实 ASI 项目（fla DeltaNet + FLAME）+ AutoDL 最便宜实例验证 NAS workflow 端到端云端训练。

---

## Context

用户要求打通"本地 NAS workflow + 云端 GPU 训练"链路，用 ASI 论文真实模型 + 训练框架（不是简化版），T1=5min/T2=15min 伪训练验证流程。AutoDL 提供 token 可 API 开实例。

关键约束：
- 模型代码 = `fla.layers.DeltaNet`（ASI 论文真实用的）
- 训练代码 = FLAME 框架的 `flame.train`（ASI 论文真实用的）
- 数据 = Wikitext-2（5MB，小数据集）
- 实例 = 3090-48G 最便宜（v-48g-350w，~¥1.5/h）
- workflow 不感知训练位置 → backend 抽象
- 所有 15 agents 按描述完成任务，时延测量正确

---

## 架构决策

### 决策 1: backend 抽象在 adapter 层（不动 workflow 核心）

`_nas_adapter.py` 是 project-specific，内部 `_train_impl()` 读 `os.environ.get("TRAIN_BACKEND", "local")` 决定调用：
- `LocalBackend`: 现有逻辑（subprocess 调本地 train.py）
- `SSHBackend`: rsync diff → ssh 远程 bash train → scp log+metrics 回

新增 `workflows/nas/helpers/train_backend.py` 提供两种实现。

### 决策 2: AutoDL 接入 = API + SSH 混合

- 用 token 调 `POST /api/v1/dev/instance/pro/create` 开实例（一次性）
- 实例开机后，AutoDL 返回 `ssh_command` + `root_password`
- 后续训练触发：SSHBackend 用 sshpass + rsync（密码登录，免配置 ssh key）

### 决策 3: 模型配置缩到 ~1M 参数

FLAME 原配置 `delta_net_340M.json` 太大（24 layers × 1024 hidden）。新配置：
- hidden_size: 256
- num_hidden_layers: 4
- num_heads: 4
- intermediate_size: 512
→ ~1.5M 参数，4090/3090 上 batch=8 seq_len=256 跑 200 step ≈ 5 min

### 决策 4: 训练入口复用 FLAME 但简化

不直接调 `bash train.sh`（要 torchrun distributed，太重）。直接调 `python -m flame.train` 单 GPU 模式：
```
python -m flame.train \
    --model.config configs/delta_nas.json \
    --training.dataset wikitext \
    --training.steps 200 \
    --training.batch_size 8 \
    --training.seq_len 256
```

如果 `flame.train` 不能简单单进程跑（torchtitan 强依赖分布式），则**写一个 train_lite.py 复用 fla.layers.DeltaNet**，保留 FLAME 的 optimizer / scheduler 配置风格，自己跑简单 LM loop。**这是真实模型 + 简化训练**的合理 trade-off。

### 决策 5: setup 跑一次后续传

第一次跑 setup 生成 contract，后续 `--session-id` 续传跳过（`check_resume.py` 已支持）。

---

## 文件清单

### 新增（11）
1. `workflows/nas/helpers/train_backend.py` — LocalBackend + SSHBackend
2. `workflows/nas/helpers/autodl_api.py` — AutoDL REST API wrapper
3. `workflows/nas/helpers/cloud_setup.md` — AutoDL 实例配置指南
4. `projects/asi/__init__.py`
5. `projects/asi/model.py` — 包装 `fla.layers.DeltaNet` 的 LM head 模型
6. `projects/asi/train.py` — Wikitext-2 LM training，step 控制
7. `projects/asi/eval.py` — held-out perplexity
8. `projects/asi/_nas_adapter.py` — 调 train_backend
9. `projects/asi/configs/delta_nas.json` — 缩小版 DeltaNet 配置
10. `projects/asi/requirements.txt`
11. `projects/asi/README.md` + `projects/asi/cloud_setup.sh`

### 修改（3）
1. `workflows/nas/helpers/_adapter_template.py` — docstring 加 backend hook 说明
2. `workflows/nas/agents/selector.md` — 修漏洞 #1（写 `tier_decision.json`）
3. `docs/status/CURRENT.md` — 任务进入

### 不动
- `workflows/nas/run_nas.py`
- `workflows/nas/workflow.json`
- `workflows/nas/helpers/run_strategy.py`
- `harness/*`

---

## 实施阶段

### Phase A: Backend 抽象 + AutoDL API（1 天）
1. 写 `train_backend.py`：定义 `TrainBackend` Protocol + `LocalBackend` + `SSHBackend`
2. 写 `autodl_api.py`：`create_instance` / `power_on/off` / `get_snapshot` / `release`
3. 用 token 实际开一个实例验证 API 可用
4. 修改 `_adapter_template.py` 加 backend hook docstring
5. 本地 LocalBackend 回归测试（mnist 跑 1 iter 不回归）

### Phase B: ASI 项目骨架（1.5 天）
1. `model.py`：包装 `fla.layers.DeltaNet` + LM head + tokenizer embedding
2. `configs/delta_nas.json`：缩小版配置
3. `train.py`：HF datasets 加载 wikitext-2，step-based loop，每 50 step log loss
4. `eval.py`：held-out perplexity
5. `_nas_adapter.py`：根据 env 选 backend
6. 本地 CPU 跑 5 step 烟雾测试（用 torch CPU）

### Phase C: 云端环境（0.5 天，用户配合）
1. 用户在 AutoDL 控制台或 API 创建 3090-48G 实例
2. SCP `cloud_setup.sh` 到实例执行：
   - clone AgentHarness repo
   - pip install：fla + flame + datasets + transformers
   - 下 wikitext-2 到 `/root/autodl-tmp/data`
3. 云端烟雾测试：`python -m projects.asi.train --steps 10`

### Phase D: setup_align 生成 contract（0.5 天）
1. 跑 setup_align 等 setup agents（ask_user 默认值）
2. baseline_runner 跑 T2=600 step 全量 baseline（~15 min）
3. 验证 `setup_contract.json` + `budget.json` + `baseline.json` 完整

### Phase E: 1-2 cycle iter 验证（0.5 天）
1. 跑 iter_1：3 个 optimizer 并发（每个改 ≤3 change point）
2. 每个 optimizer 调 SSHBackend 触发云端训练（T1=200 step）
3. analyzer 看 ranking，tier2_runner 决定是否触发 T2
4. 检查：fitness 计算、候选池、L1 memory、所有 schema 合规

### Phase F: release note + 漏洞清单（0.5 天）
1. 写 `docs/releases/2026-06-19-nas-cloud-backend.md`
2. CHANGELOG 加索引
3. 清空 CURRENT.md

---

## 已知漏洞（用户要求找的）

### 漏洞 #1（必现，必修）: `tier_decision.json` 没人写
`optimizer_*.md:31` 都读 `<session_dir>/iter_<N>/tier_decision.json`，但 workflow 中没有任何 agent 创建。**修复**：让 `selector.md` 写。

### 漏洞 #2（潜在）: setup contract 缺 backend 字段
adapter 不知道从哪读 backend 配置。**修复**：通过 env var `TRAIN_BACKEND` 读，contract 不动。

### 漏洞 #3-5（待 Phase E 暴露）
通过实际跑 cycle 找，至少要找 3 个写进 release note。

---

## 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| AutoDL SSH 抖动 | SSHBackend retry 3 次指数退避，失败 loud raise |
| FLAME 单进程跑不通 | 退回到自写 train_lite.py，复用 `fla.layers.DeltaNet` |
| 训练时长估算不准 | baseline 跑后实际测量 step/sec，校准 T1/T2 step 数 |
| fla lib 装不上（triton 编译） | 用 pip 预编译 wheel；fallback：CPU 模式跑极小模型 |
| AutoDL token 余额不足 | 先调 API 查余额 |

---

## 验证

- Phase A 后：mnist session 跑 1 iter 不回归
- Phase B 后：`python projects/asi/train.py --steps 5` 本地 CPU 跑通
- Phase C 后：云端 `python -m projects.asi.train --steps 50` 跑通
- Phase D 后：contract 文件齐全
- Phase E 后：iter_1 三个 optimizer 都有 eval_result.json + candidates.json 更新
- Phase F 后：release note + CHANGELOG 完整
