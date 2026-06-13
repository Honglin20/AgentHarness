# adapter_generator (scout sub_agent task spec)

> 本文件是 scout 的 sub_agent `adapter_generator` 的 task spec。
> scout 在 Wave 1 里按本 spec 构造 task 字符串，issue sub_agent 调用（`isolation="none"`）。
> 本文件不是独立 agent（不在 workflow.json 里），只是 spec 文档。

## 角色

在用户项目根目录生成 `.nas_runner.py` —— 一个 sidecar CLI 脚本，**作为 NAS workflow 与用户项目的唯一契约边界**。后续所有 agent（baseline_runner / trainer / refiner）只调 `.nas_runner.py`，绝不直接调用户脚本。

## 输入（scout 在 task 字符串里显式传入）

- `working_dir`（用户项目绝对路径）
- `session_dir`（写 adapter_report.json 的位置）
- `helpers_dir`（export 子命令会用到 `<helpers_dir>/export_onnx.py`）
- `workflow_dir`（参考资源位置，如本 spec 文件）

## 契约（必须满足）

`.nas_runner.py` 必须支持 4 个 CLI 子命令，**stdout 最后一行输出指定 JSON**（其他日志走 stderr，不污染 stdout）：

### 1. `smoke` —— 快速验证（scout 用来 sanity check）

```bash
python .nas_runner.py smoke [--epochs 1] [--data-ratio 0.1]
```

stdout 最后一行 JSON：
```json
{
  "ok": true,
  "checkpoint": "<path or null>",
  "metrics": {"<name>": <val>, ...},
  "duration_sec": 12.4,
  "stderr_tail": "<last 500 chars of stderr, only if not ok>"
}
```

语义：用最小配置（默认 1 epoch、可选小数据）跑一次训练，验证整条链路通。

### 2. `train` —— 完整训练入口

```bash
python .nas_runner.py train --epochs N --data-ratio R --output CKPT_PATH
```

stdout 最后一行 JSON：
```json
{
  "checkpoint": "<CKPT_PATH or actual path>",
  "metrics": {"<name>": <val>, ...},
  "loss_curve": [<float>, ...],
  "params": 8970,
  "duration_sec": 45.2
}
```

约束：
- `--epochs` / `--data-ratio` 收到时尽量传给用户项目；如果某维度用户项目无法控制，**仍正常跑**（用项目默认值），但 stderr 写 warning
- `--output` 是建议路径；如果用户项目硬编码 checkpoint 路径，写到用户路径然后在 JSON 里返回实际路径
- `metrics` 至少包含 1 个用户项目认可的指标（如 acc / loss / bleu）
- `loss_curve` 是训练过程中的 loss 采样（每 epoch 1 个点足够；如果用户脚本不输出，留空数组 `[]`）

### 3. `evaluate` —— 单独评估 checkpoint

```bash
python .nas_runner.py evaluate --checkpoint CKPT_PATH
```

stdout 最后一行 JSON：
```json
{
  "metrics": {"<name>": <val>, ...},
  "latency_ms": 1.53,
  "params": 8970
}
```

约束：
- 必须基于给定 checkpoint 评估，不重训
- `latency_ms` 是推理延迟（per sample 或 per batch，在 metrics 里注明 batch_size）
- 如果用户项目没有独立 evaluate 脚本，但 train.py 支持 `--eval-only` / `--evaluate` flag → 用它
- 如果完全没有 evaluate 入口 → 从 checkpoint 加载模型 + 跑一次 dummy inference 测延迟，metrics 留空 `{}`

### 4. `export` —— 导出 ONNX

```bash
python .nas_runner.py export --checkpoint CKPT_PATH --out ONNX_PATH
```

stdout 最后一行 JSON：
```json
{
  "onnx_path": "<ONNX_PATH>",
  "input_signature": "tensor(1,3,224,224) | tuple(2) | list(3) | dict(user,item)"
}
```

约束：
- 委托给 `<helpers_dir>/export_onnx.py`（已有逻辑，自动调 `model.dummy_inputs()` 推导 forward 签名）
- 缺 `dummy_inputs` → export_onnx.py 已有 fallback（append 到 model.py 末尾重试）
- 失败 → stdout JSON 的 `ok` 字段为 false，`error` 字段写原因

## 自由度（你判断，不规定流程）

| 决策点 | 选项 | 你怎么判断 |
|---|---|---|
| subprocess vs import | `subprocess.run([sys.executable, "train.py", ...])` / `from train import train_model; train_model(...)` | 看用户项目结构。脚本式优先 subprocess；包式（有 `__init__.py` + `pyproject.toml` 入口）可 import |
| epochs 怎么传 | CLI flag / 改 config 文件 / env var / 硬编码 | 跑 `<entry> --help`；没有 flag 就看 config 文件；都没有就 grep `epochs\s*=\s*\d+` |
| data_ratio 怎么传 | 同上 | 同上 |
| evaluate 来源 | 独立脚本 / train.py 的 eval 模式 / 训练产物读 metrics.json | 看用户项目里有没有 `evaluate.py` 或 `--eval` flag 或训练结束写 metrics 文件 |
| metrics 解析 | stdout regex / stderr regex / 写入的 json 文件 / tensorboard log | 跑一次原命令看输出格式 |
| 模型加载（export 用） | `from model import Net` / `torch.load(ckpt)` / 用户项目的 loader 函数 | 看 model.py 或 README |

## 硬性约束

1. **不修改用户已有任何代码文件**（read-only on user code）
2. 可新增：
   - `<working_dir>/.nas_runner.py`
   - `<working_dir>/.gitignore`（追加一行 `.nas_runner.py`；若文件不存在则创建）
3. **必须通过 parity test**（见下）—— 这是唯一保证 adapter 正确性的关卡
4. `.nas_runner.py` 必须 self-contained —— 可独立 `python .nas_runner.py ...` 跑，不 import NAS workflow 代码
5. `.nas_runner.py` 写到 `<working_dir>`，**不写到 session_dir**（用户可见、可编辑、gitignored）

## Parity test（强制，不可跳过）

确保 adapter 与用户原脚本**计算等价**。两种策略自选：

### 策略 A — `quick_parity`（推荐，便宜）

适用：训练入口能控制 epochs / data_ratio（即使只能改 config 文件也算）。

```
1. 确定用户"原命令" — 例如 `python train.py --config config.yaml`
   （从 README / pyproject scripts / Makefile / shell history 推断；不确定 → ask scout 转 ask_user）

2. 跑原命令 with 最小配置：
   - epochs = 1（原命令如果支持 --epochs 就加；否则改 config 文件临时设 epochs=1，跑完恢复）
   - data_ratio = 0.1 if 可控 else 1.0
   - timeout = 300s（超时 → 切策略 B 或 ask_user）
   → 解析 stdout / metrics file → original_metrics

3. 跑 .nas_runner.py train --epochs 1 --data-ratio <同上>
   → 从 stdout JSON 拿 adapter_metrics

4. 比对（按 metric 方向）：
   - acc / bleu / rouge 等 higher-better: |adapter - original| / |original| ≤ 0.01
   - loss / perplexity / wer 等 lower-better: 同上 ≤ 0.05（loss 噪声大）
   - latency / params: 完全相等（确定性量）

5. 通过 → adapter_report.parity_result.passed = true，写 delta_rel
   失败 → 进 retry 流程
```

### 策略 B — `eval_only_parity`（训练太贵时）

适用：训练单次 > 5 分钟，但用户有现成 checkpoint + evaluate 入口。

```
1. 找用户已有 checkpoint（如 checkpoints/best.pt、runs/latest.pth）
   找不到 → 切策略 A 或 ask_user

2. 跑用户的 evaluate 脚本（或 train.py --eval-only）→ original_metrics

3. 跑 .nas_runner.py evaluate --checkpoint <同上> → adapter_metrics

4. 比对同策略 A
```

### 容差理由

PyTorch 默认非确定性（cuDNN algorithm 选择、dataloader worker shuffle、Python hash 随机化影响 dict 顺序），即使同命令两次跑也会有 0.1%~1% 差异。**1% acc / 5% loss 是合理 noise floor**；超出意味着 adapter 逻辑有 bug。

### Retry 流程（最多 2 轮）

```
失败 → 看 delta_rel 推断错误源：

  delta 很大（> 50%）→ 大概率命令构造错了
    - flag 名拼错？ (用了 --epochs 但 train.py 是 --num_epochs)
    - config key 错？ (patched 'training.epochs' 但实际是 'epochs.train')
    - 数据集路径错？ (相对路径 vs 绝对路径，cwd 不对)

  delta 中等（5%~50%）→ 大概率 metrics 解析错了
    - 字段名错？ (parse 'accuracy' 但 train.py 打 'acc')
    - 单位错？ (0.78 vs 78%)
    - 取错 epoch 的值？ (取了 epoch 0 而非 epoch 1)

  delta 小（1%~5%）→ 可能就是噪声
    - 重跑一次原命令确认 noise floor
    - 如果两次原命令差异也这么大 → tolerance 太严，放宽到 delta_rel ≤ 实测 noise
    - 仍超 → 进 retry

  轮 1: 改 .nas_runner.py（按上述推断），重测 parity
  轮 2: 换实现策略（subprocess ↔ import；改 config ↔ env var），重测
  仍失败 → 返回失败结果给 scout（scout 会 ask_user）
```

## 失败升级（返回给 scout）

2 轮 retry 仍失败时，**不要静默**。返回结构化失败结果：

```json
{
  "status": "parity_failed",
  "retries": 2,
  "original_command": "python train.py --config config.yaml",
  "adapter_path": "<working_dir>/.nas_runner.py",
  "last_original_metrics": {...},
  "last_adapter_metrics": {...},
  "last_delta_rel": {...},
  "diagnostic_hypotheses": [
    "flag name mismatch: I used --epochs but train.py --help shows --num_epochs",
    "metric field mismatch: I parsed 'accuracy' but train.py prints 'acc'"
  ],
  "sidecar_contents": "<full .nas_runner.py content for scout to show user>"
}
```

scout 看到这个结果 → 调 `ask_user` 工具（scout 是顶层 agent 可用 ask_user）展示诊断信息 → 用户给提示 → scout 重新 issue adapter_generator sub_agent，task 里附上用户提示。

## 输出

成功时写两个文件：

### 1. `<working_dir>/.nas_runner.py`

self-contained Python 脚本，支持上述 4 子命令。stdout 严格按契约输出 JSON。

### 2. `<session_dir>/adapter_report.json`

```json
{
  "adapter_path": "<working_dir>/.nas_runner.py",
  "original_train_command": "python train.py --config config.yaml",
  "internal_train_command": "subprocess: python train.py --config config.yaml --epochs N",
  "controllable": ["epochs", "data_ratio"],
  "uncontrollable": ["output_checkpoint"],
  "defaults": {
    "epochs": 10,
    "data_ratio": 1.0,
    "batch_size": 32
  },
  "evaluate_source": "in_train",
  "export_strategy": "helpers/export_onnx.py + dummy_inputs",
  "parity_result": {
    "strategy": "quick_parity",
    "config_used": {"epochs": 1, "data_ratio": 0.1},
    "original_metrics": {"acc": 0.4523, "loss": 1.8234},
    "adapter_metrics": {"acc": 0.4519, "loss": 1.8241},
    "delta_rel": {"acc": 0.0009, "loss": 0.0004},
    "tolerance": {"acc_rel": 0.01, "loss_rel": 0.05},
    "passed": true,
    "retries": 0
  },
  "smoke_result": {
    "ok": true,
    "duration_sec": 12.4,
    "checkpoint": "<worktree>/checkpoints/smoke.pt"
  },
  "notes": "data_ratio 通过 config.yaml 的 data.subset_ratio 控制；epochs 通过 --epochs flag；evaluate 是 train.py 的 --eval-only 模式"
}
```

**字段说明**：

- `controllable` / `uncontrollable`：维度名列表（`"epochs"` / `"data_ratio"` / `"output_checkpoint"`），决定 trainer/refiner 能否用该维度做 tier 区分
- `defaults`：你在探测时观察到的**用户项目默认值**（如 config.yaml 里的 `epochs: 10`、argparse default、或硬编码值）。baseline_runner 读 `defaults.epochs` 估算 `total_epochs`；探测不到的字段填 `null`
- `evaluate_source`：`"subprocess"`（独立 evaluate.py）/ `"in_train"`（train.py 的 --eval 模式）/ `"metrics_file"`（从训练产物读）/ `"checkpoint_only"`（无 evaluate 入口，只能加载 ckpt 测 latency）
- `parity_result.delta_rel`：`|adapter - original| / |original|`，按 metric 名 keyed
- `notes`：自由文本，给下游 agent 提示（如"epochs 是硬编码，trainer 不要试图 tier 控 epochs"）

### 3. 返回给 scout 的 summary

```json
{
  "status": "ok",
  "adapter_path": "<working_dir>/.nas_runner.py",
  "report_path": "<session_dir>/adapter_report.json",
  "controllable": ["epochs", "data_ratio"],
  "uncontrollable": ["output_checkpoint"],
  "parity_passed": true,
  "summary": "adapter ready: train via subprocess, evaluate via --eval-only, parity ok (delta_acc=0.0009)"
}
```

## 严禁

- ❌ 修改用户任何已有文件（除 `.gitignore` 追加一行）
- ❌ 假设用户用 PyTorch（可能是 TF/JAX/Flax；只要能跑出 metric 就行）
- ❌ import NAS workflow 代码到 `.nas_runner.py`（必须 self-contained）
- ❌ 跳过 parity test（这是唯一保证正确性的关卡；时间紧也不能跳）
- ❌ 把 `.nas_runner.py` 写到 session_dir（必须写到 working_dir，用户可见可编辑）
- ❌ 静默吞错（任何失败都要结构化返回，让 scout 决策）

## 参考骨架（不是模板，可自由改写）

下面是一个**最小可工作的参考实现**，展示 4 子命令的形态。**你可以基于它改，也可以从零写**——只要满足契约。

```python
#!/usr/bin/env python
"""NAS adapter — auto-generated by adapter_generator. Edit freely."""
import argparse, json, subprocess, sys, re, os, shutil
from pathlib import Path

# ============ Detected config (you fill after probing) ============
TRAIN_SCRIPT = "train.py"
TRAIN_EPOCHS_VIA = "cli_flag"           # cli_flag | config_file | env_var | unsupported
TRAIN_EPOCHS_FLAG = "--epochs"          # if cli_flag
TRAIN_EPOCHS_CONFIG = ("config.yaml", "training.epochs")  # if config_file
TRAIN_EPOCHS_ENV = "EPOCHS"             # if env_var

DATA_RATIO_VIA = "unsupported"          # if user project doesn't support subset
DATA_RATIO_FLAG = "--data-ratio"
DATA_RATIO_CONFIG = ("config.yaml", "data.subset_ratio")

OUTPUT_VIA = "hardcoded"                # user project writes to fixed path
OUTPUT_DEFAULT = "checkpoints/best.pt"

EVALUATE_MODE = "in_train"              # subprocess | in_train | metrics_file
EVALUATE_SCRIPT = "evaluate.py"
EVALUATE_FLAG = "--eval-only"
METRICS_FILE = None                     # if evaluate reads from file

METRICS_PARSE = "stdout_regex"          # stdout_regex | metrics_file | tb_log
METRICS_REGEX = r'"acc":\s*([\d.]+).*"loss":\s*([\d.]+)'
# ===================================================================

def _run(cmd, timeout=600, env=None):
    """subprocess.run wrapper, returns (rc, stdout, stderr)."""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout, r.stderr

def _emit(payload):
    """Last line of stdout must be the JSON result."""
    print(json.dumps(payload))

def _parse_metrics(stdout, stderr=""):
    if METRICS_PARSE == "metrics_file" and METRICS_FILE and Path(METRICS_FILE).exists():
        return json.loads(Path(METRICS_FILE).read_text())
    m = re.search(METRICS_REGEX, stdout)
    if m:
        # Adapt to your regex groups:
        return {"acc": float(m.group(1)), "loss": float(m.group(2))}
    return {}

class _Backup:
    """File backup/restore for config_file mutation."""
    def __init__(self, path):
        self.path = path
        self.bak = path + f".nasbak.{os.urandom(4).hex()}"
        shutil.copy(path, self.bak)
    def restore(self):
        shutil.copy(self.bak, self.path)
        os.remove(self.bak)

def _set_dotted(cfg, dotted_key, value):
    """Set nested dict key by 'a.b.c' path."""
    keys = dotted_key.split(".")
    for k in keys[:-1]:
        cfg = cfg.setdefault(k, {})
    cfg[keys[-1]] = value

def _apply_epochs(cmd, env, epochs, backups):
    if TRAIN_EPOCHS_VIA == "cli_flag":
        cmd += [TRAIN_EPOCHS_FLAG, str(epochs)]
    elif TRAIN_EPOCHS_VIA == "config_file":
        # Load YAML/JSON, set key, write back
        import yaml  # or json, depending on file ext
        cfg_file = TRAIN_EPOCHS_CONFIG[0]
        bak = _Backup(cfg_file)
        backups.append(bak)
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        _set_dotted(cfg, TRAIN_EPOCHS_CONFIG[1], epochs)
        with open(cfg_file, "w") as f:
            yaml.dump(cfg, f)
    elif TRAIN_EPOCHS_VIA == "env_var":
        env[TRAIN_EPOCHS_ENV] = str(epochs)
    elif TRAIN_EPOCHS_VIA == "unsupported":
        sys.stderr.write(f"[nas_runner] warning: epochs is hardcoded, ignoring epochs={epochs}\n")

# Similar _apply_data_ratio, _apply_output...

def smoke(args):
    return train_impl(epochs=args.epochs or 1, data_ratio=args.data_ratio or 1.0,
                      output=None, is_smoke=True)

def train_impl(epochs, data_ratio, output, is_smoke=False):
    cmd = [sys.executable, TRAIN_SCRIPT]
    env = os.environ.copy()
    backups = []
    try:
        _apply_epochs(cmd, env, epochs, backups)
        # _apply_data_ratio(cmd, env, data_ratio, backups)
        # _apply_output(cmd, env, output, backups)
        rc, out, err = _run(cmd, env=env)
        metrics = _parse_metrics(out)
        # Detect checkpoint path
        ckpt = output or OUTPUT_DEFAULT
        return {
            "ok": rc == 0,
            "checkpoint": ckpt if rc == 0 else None,
            "metrics": metrics,
            "duration_sec": 0.0,  # measure actual
            "stderr_tail": err[-500:] if rc != 0 else "",
        }
    finally:
        for b in backups:
            b.restore()

def train(args):
    res = train_impl(epochs=args.epochs, data_ratio=args.data_ratio,
                     output=args.output, is_smoke=False)
    _emit(res)

def evaluate(args):
    if EVALUATE_MODE == "subprocess":
        cmd = [sys.executable, EVALUATE_SCRIPT, "--checkpoint", args.checkpoint]
        rc, out, err = _run(cmd)
        metrics = _parse_metrics(out)
    elif EVALUATE_MODE == "in_train":
        cmd = [sys.executable, TRAIN_SCRIPT, EVALUATE_FLAG, "--checkpoint", args.checkpoint]
        rc, out, err = _run(cmd)
        metrics = _parse_metrics(out)
    else:  # metrics_file
        metrics = json.loads(Path(METRICS_FILE).read_text()) if Path(METRICS_FILE).exists() else {}
    # Measure latency (optional; can be empty)
    _emit({"metrics": metrics, "latency_ms": None, "params": None})

def export(args):
    helpers_dir = os.environ.get("NAS_HELPERS_DIR", ".")
    cmd = [sys.executable, f"{helpers_dir}/export_onnx.py",
           "--checkpoint", args.checkpoint, "--out", args.out, "--model-dir", "."]
    rc, out, err = _run(cmd)
    if rc == 0:
        _emit({"onnx_path": args.out, "input_signature": "(see export_onnx output)"})
    else:
        _emit({"ok": False, "error": err[-500:]})

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("smoke")
    s.add_argument("--epochs", type=int, default=None)
    s.add_argument("--data-ratio", type=float, default=None)

    t = sub.add_parser("train")
    t.add_argument("--epochs", type=int, required=True)
    t.add_argument("--data-ratio", type=float, default=1.0)
    t.add_argument("--output", default=None)

    e = sub.add_parser("evaluate")
    e.add_argument("--checkpoint", required=True)

    x = sub.add_parser("export")
    x.add_argument("--checkpoint", required=True)
    x.add_argument("--out", required=True)

    args = p.parse_args()
    {"smoke": smoke, "train": train, "evaluate": evaluate, "export": export}[args.cmd](args)
```

**注意**：这是参考，不是模板。你需要根据探测结果填 `TRAIN_EPOCHS_VIA` / `EVALUATE_MODE` / `METRICS_PARSE` 等配置，并改写 `_apply_*` 函数适配用户的实际机制。如果用户项目结构特殊（如 Hydra config、import-based 入口），完全可以推翻这个骨架从零写。

## 完成后的自检 checklist

- [ ] `.nas_runner.py` 在 `<working_dir>`，能独立 `python .nas_runner.py smoke` 跑通
- [ ] `<working_dir>/.gitignore` 包含 `.nas_runner.py`
- [ ] 4 个子命令的 stdout 最后一行都是合法 JSON
- [ ] parity_result.passed = true（或 status = "parity_failed" 已结构化返回）
- [ ] adapter_report.json 已写到 `<session_dir>`
- [ ] 用户原有代码无任何修改（`git -C <working_dir> status` 应该 clean，只有新增的 `.nas_runner.py` + `.gitignore` 改动）
