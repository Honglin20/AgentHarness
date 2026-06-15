# adapter_generator (scout sub_agent task spec)

> 本文件是 scout 的 sub_agent `adapter_generator` 的 task spec。
> scout 在 Wave 1 里按本 spec 构造 task 字符串，issue sub_agent 调用（isolation="none"）。
> 本文件不是独立 agent（不在 workflow.json 里），只是 spec 文档。

## 角色

从 `workflows/nas/helpers/_adapter_template.py`（NAS 团队维护的模板）+ project_analysis.json 填充 **3 个占位符**，生成 `<working_dir>/_nas_adapter.py`。验证 **smoke 三件套**（train + export_onnx + measure_latency）全 OK 才返回。

**不再生成完整 CLI sidecar**（旧 `.nas_runner.py` 方案已删除，决策 6）。
**不再做 parity test**（要求太严，研发态代码适配失败率高，决策 3）。

## 输入（scout 在 task 字符串里显式传入）

- `working_dir`（用户项目绝对路径）
- `session_dir`（写 adapter_report.json 的位置）
- `helpers_dir`（`<helpers_dir>/_adapter_template.py` + `<helpers_dir>/export_onnx.py` 等）
- `workflow_dir`（参考资源位置）
- `project_analysis` dict（含 model_class / model_module / model_init_args / train_entry / train_signature / eval_entry / weights_path / epochs_controllable / epochs_control_mechanism / epochs_default）
- workflow inputs 可选：`dummy_inputs`（用户已声明则直接用，跳过探测）

## 契约

`_nas_adapter.py` 必须实现 4 个公共函数（来自模板，**不修改**）：
- `get_model(**overrides) -> nn.Module`
- `train(model, epochs=None, output=None) -> dict`
- `evaluate(model, checkpoint=None) -> dict`
- `export_onnx(model, out_path) -> str`

LLM **只填 3 个占位符函数**（替换默认 raise NotImplementedError body）：
- `_construct_model(**overrides) -> nn.Module` [MODEL_IMPORT]
- `_train_impl(model, epochs, output) -> dict` [TRAIN_WRAPPER]
- `_eval_impl(model, checkpoint) -> dict` [EVAL_WRAPPER]

模板已实现所有"基础设施"（参数计数、state_dict 加载、latency 测量、ONNX 委托、failure 包装、smoke CLI）—— LLM 不写这些。

## 步骤

### 1. 读模板 + project_analysis

```bash
cat <helpers_dir>/_adapter_template.py
cat <session_dir>/project_analysis.json
```

理解模板结构：
- 顶部常量（HELPERS_DIR / WEIGHTS_PATH / DUMMY_INPUTS_VALUE）—— adapter_generator 填
- 占位符函数（3 个，默认 raise NotImplementedError）—— adapter_generator 填 body
- Public API（4 个，NAS 团队写死）—— **不动**
- Helpers（_safe_param_count / _load_state_dict / _measure_latency / _failure_result）—— **不动**
- CLI smoke 入口 —— **不动**

### 2. 填 MODEL_IMPORT 占位符

基于 `project_analysis.model_class` / `model_module` / `model_init_args`：

```python
def _construct_model(**overrides):
    from <model_module> import <model_class>
    kwargs = {"<key>": <value>, ...}  # from model_init_args
    kwargs.update(overrides)
    return <model_class>(**kwargs)
```

### 3. 填 TRAIN_WRAPPER 占位符

基于 `project_analysis.train_entry` + `epochs_control_mechanism`：

#### function_arg 模式（train_entry 是函数 + 接受 epochs 参数）

```python
def _train_impl(model, epochs, output):
    from <train_module> import <train_func>
    kwargs = {}
    if epochs is not None:
        kwargs["epochs"] = epochs
    result = <train_func>(model=model, **kwargs)
    # result 可能是 dict / tuple / None
    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    loss_curve = result.get("loss_curve", []) if isinstance(result, dict) else []
    ckpt = result.get("checkpoint") if isinstance(result, dict) else None
    if output is not None and ckpt is None:
        import torch
        torch.save(model.state_dict(), output)
        ckpt = str(output)
    return {"metrics": metrics, "loss_curve": loss_curve, "checkpoint": ckpt}
```

#### cli_flag 模式（train.py 接受 --epochs flag）

```python
def _train_impl(model, epochs, output):
    import subprocess, sys
    cmd = [sys.executable, "<train_module>.py"]
    if epochs is not None:
        cmd += ["--epochs", str(epochs)]
    r = subprocess.run(cmd, cwd="<working_dir>", capture_output=True, text=True)
    # 解析 stdout 拿 metrics + loss_curve（用 regex 或 json）
    ...
    return {"metrics": metrics, "loss_curve": loss_curve, "checkpoint": None}
```

#### config_file 模式（修改 yaml/json 临时设 epochs，finally 恢复）

类似 cli_flag，但通过 patch config 文件实现。

#### hardcoded 模式（无法控制 epochs）

```python
def _train_impl(model, epochs, output):
    if epochs is not None:
        import sys
        sys.stderr.write("[adapter] warning: epochs is hardcoded, ignoring epochs=%s\n" % epochs)
    # 跑用户默认训练
    ...
```

### 4. 填 EVAL_WRAPPER 占位符

基于 `project_analysis.eval_entry`：

#### 有 eval_entry

```python
def _eval_impl(model, checkpoint):
    from <eval_module> import <eval_func>
    metrics = <eval_func>(model=model)
    return {"metrics": metrics}
```

#### eval_entry == "NOT_FOUND"（用户没独立 eval 函数）

build minimal inference loop（从 data_loader_entry 拿数据，或从 dummy_inputs 跑 forward）：

```python
def _eval_impl(model, checkpoint):
    # 如果 data_loader_entry 可用
    from <data_module> import <data_func>
    loader = <data_func>(batch_size=32, train=False)
    correct, total = 0, 0
    import torch
    with torch.no_grad():
        for x, y in loader:
            pred = model(x).argmax(dim=1)
            correct += (pred == y).sum().item()
            total += y.numel()
    return {"metrics": {"acc": correct / total if total else 0.0}}
```

如果连 data_loader_entry 都没有 → 返回空 metrics `{"metrics": {}}`，judger 会用 train metrics 排序。

### 5. 填配置常量

```python
HELPERS_DIR = Path("<helpers_dir 绝对路径>")  # adapter_generator 填绝对路径
WEIGHTS_PATH = "<weights_path or NOT_FOUND>"  # from project_analysis
DUMMY_INPUTS_VALUE = <workflow inputs 声明的 shape 或 None>  # 见 §dummy_inputs 处理
```

### 6. 写 _nas_adapter.py

把模板内容 + 填好的占位符 + 配置常量拼成完整文件，写到 `<working_dir>/_nas_adapter.py`。

追加 `<working_dir>/.gitignore` 一行 `_nas_adapter.py`（若不存在则创建）。

### 7. Smoke 三件套验证

```bash
python <working_dir>/_nas_adapter.py smoke
```

`smoke` 命令内部跑：
- `get_model()` 实例化 model
- `train(epochs=1)` 跑训练（验证 ok=true + metrics 非空）
- `evaluate()` 跑评估（验证 ok=true + latency_ms > 0）
- `export_onnx()` 跑 ONNX 导出（验证返回路径）

三件套任一失败 → 看 stderr 推断原因，retry（改占位符实现，**最多 2 次**）。

仍失败 → 返回结构化失败（见 §失败升级），让 scout 触发 ask_user。

### 8. 写 adapter_report.json

成功后写到 `<session_dir>/adapter_report.json`：

```json
{
  "adapter_path": "<working_dir>/_nas_adapter.py",
  "project_analysis_path": "<session_dir>/project_analysis.json",
  "epochs_controllable": <bool from project_analysis>,
  "defaults": {
    "epochs": <int from project_analysis or null>,
    "batch_size": null
  },
  "evaluate_source": "subprocess | in_train | metrics_file | checkpoint_only",
  "export_strategy": "helpers/export_onnx.py + dummy_inputs",
  "smoke_result": {
    "train_ok": true,
    "export_ok": true,
    "latency_ok": true,
    "latency_ms": <float>,
    "error": null
  },
  "notes": "<free text>"
}
```

### 9. 返回 scout 的 summary

```json
{
  "status": "ok",
  "adapter_path": "<working_dir>/_nas_adapter.py",
  "report_path": "<session_dir>/adapter_report.json",
  "epochs_controllable": <bool>,
  "smoke_pass": true,
  "summary": "adapter ready: train via <mechanism>, eval via <source>, smoke ok (latency=Xms)"
}
```

## dummy_inputs 处理（关键）

### 用户在 workflow inputs 声明 dummy_inputs

直接使用，模板配置常量 `DUMMY_INPUTS_VALUE = <声明值>`。**不探测，不问用户**。

### 未声明

adapter_generator 在 smoke 之前探测：

1. **优先**：实例化 model，调 `model.dummy_inputs()`（如果 model 实现了这个方法）→ 用返回值推 shape/dtype
2. **次选**：从 `data_loader_entry` 抓第一个 batch，推 shape/dtype
3. **最后**：从 `model.forward` 签名推断（不稳定，仅 emergency fallback）

**探测结果必须 ask_user 报备**（决策 4）：

```
ONNX export 需要 dummy inputs。
我从 <来源：model.dummy_inputs / DataLoader first batch / forward signature> 推断：shape=<X>, dtype=<Y>。
这个对吗？

[对，使用] / [我手动指定 shape] / [跳过 ONNX export]
```

用户确认 → 写入 `DUMMY_INPUTS_VALUE = {"shape": [...], "dtype": "..."}`。
用户手动指定 → 用用户给的值。
用户跳过 → `DUMMY_INPUTS_VALUE = None`（latency 测量返回 0.0，ONNX export 走 export_onnx.py 的 fallback）。

## 失败升级

smoke 三件套 2 轮 retry 仍失败 → **不要静默**。返回结构化失败：

```json
{
  "status": "smoke_failed",
  "retries": 2,
  "failed_step": "train | evaluate | export_onnx",
  "error_trace": "<stack>",
  "diagnostic_hypotheses": [
    "model_class import failed: <reason>",
    "train function signature mismatch: expected <sig>, got <actual>",
    "evaluate function returned wrong shape"
  ]
}
```

scout 看到 `status="smoke_failed"` → 触发 ask_user 兜底（让用户补字段 / 手动指定 train_entry / abort）。

## 自由度（你判断，不规定流程）

| 决策点 | 选项 |
|---|---|
| 训练调用方式 | function_arg / cli_flag / config_file / hardcoded（基于 project_analysis.epochs_control_mechanism）|
| 评估来源 | subprocess / in_train / metrics_file / checkpoint_only（基于 project_analysis.eval_entry）|
| metrics 解析 | function return value（preferred）/ stdout regex / metrics file |
| 模型加载 | 直接 import / torch.load + load_state_dict |

## 严禁

- ❌ 修改用户任何已有文件（除 `_nas_adapter.py` + `.gitignore` 追加一行）
- ❌ 修改 `_adapter_template.py`（NAS 团队维护，**只读**）
- ❌ 修改 Public API 4 个函数（`get_model` / `train` / `evaluate` / `export_onnx`）—— 只填 3 个占位符 body
- ❌ 跳过 smoke 三件套（这是唯一保证 adapter 正确性的关卡；时间紧也不能跳）
- ❌ 把 `_nas_adapter.py` 写到 session_dir（必须写到 working_dir，用户可见可编辑）
- ❌ 静默吞错（任何失败都要结构化返回，让 scout 决策）
- ❌ 假设用户用 PyTorch（可能是 TF/JAX/Flax；只要能跑出 metric 就行）
- ❌ 重新实现 Public API / Helpers（模板已写好，LLM 只填占位符）
- ❌ dummy_inputs 未声明时跳过 ask_user 报备（决策 4 强制要求）
