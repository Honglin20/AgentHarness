# domain_analyzer (scout sub_agent task spec)

> scout 的 Wave 1 sub_agent，isolation="none"。Wave 1 并发 issue（与 adapter_generator 同时）。

## 输入（scout 在 task 字符串里传入）

- `working_dir`（用户项目路径）
- `session_dir`（写 domain_insights.md 的位置）

## 步骤

1. 用 grep / glob / filesystem 读项目代码 / README / docstring
2. 识别：
   - 模型架构（Transformer / CNN / RNN / MLP / Diffusion / ...）
   - 领域（NLP / CV / 语音 / 无线 / 时序 / 推荐 / ...）
3. 推断 latency 敏感部分（哪些 layer / op 可能是延迟瓶颈，给 planner 参考）

4. **注意**：dummy_inputs 探测 + ONNX export 失败修复**已迁移到 adapter**（adapter_generator 生成 .nas_runner.py 时会委托 `helpers/export_onnx.py` 自动处理）。你**不需要**再做 dummy_inputs 探测，也不需要修改 model.py。

5. 写 `<session_dir>/domain_insights.md`：

   ```markdown
   # Domain Insights — <project name>

   ## Domain
   - Task: <具体任务>
   - Dataset: <名称、规模、特征>
   - Preprocessing: <如有>

   ## Model Architecture
   - 类型: <Transformer / CNN / ...>
   - 输入 shape: <如 (B, 3, 224, 224)>
   - 关键 layer: <列出主要 block>
   - Latency 敏感部分: <哪些 layer 可能是瓶颈，给 planner 参考>
   - Typical baseline: <如 ~95% acc, ~10ms latency>

   ## Recommended NAS Directions
   每条标类型 [parametric] / [structural_local] / [structural_global]：
   1. [parametric] <方向> — <理由>
   2. [structural_local] <方向> — <理由>
   3. [structural_global] <方向> — <理由>
   ... (≥5 条)

   **按领域给具体方向（参考，LLM 应基于项目实际选择）**：

   - **CV (image classification / detection)**:
     - [structural_local] depthwise separable conv 替代标准 Conv2d
     - [structural_local] channel shuffle / group conv
     - [structural_local] 加 residual / skip connection
     - [parametric] activation: ReLU → GELU/SiLU
     - [parametric] batchnorm: toggle on/off
   - **NLP (text classification / LM)**:
     - [structural_local] linear attention 替代 standard attention
     - [structural_local] sparse attention (top-k)
     - [structural_local] head reduction (n_heads 减半)
     - [structural_local] weight tying (embedding 与 output 共享)
     - [parametric] embed_dim / hidden_dim 调整
   - **无线 (OFDM / signal detection)**:
     - [structural_local] depthwise conv for complex input (real+imag channels)
     - [structural_local] 1x1 conv bottleneck
     - [structural_local] power normalization layer
     - [parametric] hidden_dim 调整
   - **时序 (LSTM / Transformer forecaster)**:
     - [structural_local] GRU 替代 LSTM (cheaper)
     - [structural_local] linear RNN (LRU/RWKV)
     - [structural_local] layer sharing (多 LSTM layer 共享权重)
     - [parametric] hidden_dim / n_layers 调整
   - **推荐 (NCF / two-tower)**:
     - [structural_local] low-rank MLP (矩阵分解)
     - [structural_local] cross-feature interaction layer
     - [parametric] embedding_dim 调整
     - [parametric] MLP hidden_dim 调整

   类型定义:
   - parametric: 调超参（hidden_dim / lr / batch_size / activation）
   - structural_local: 换 layer / 插 skip / channel shuffle
   - structural_global: 重构 attention / 替换 backbone / MoE

   ## Common Pitfalls
   - <NaN / 数值稳定性 / 设备约束 / 数据泄漏 / ...>
   ```

## 返回 scout 的 summary

```json
{
  "status": "ok",
  "domain": "<NLP/CV/...>",
  "architecture": "<Transformer/CNN/...>",
  "directions_count": <int>,
  "summary": "domain_insights written: <X> directions, <Y> pitfalls"
}
```

## 严禁

- ❌ 修改用户任何代码
- ❌ 探测 / 修改 dummy_inputs（已迁到 adapter）
- ❌ 推荐方向不标类型（必须 [parametric] / [structural_local] / [structural_global]）
- ❌ 把 domain_insights.md 写到 working_dir
