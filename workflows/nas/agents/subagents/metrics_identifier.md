# metrics_identifier (scout sub_agent task spec)

> scout 的 Wave 3 sub_agent，isolation="none"。baseline.json 写完后并发 issue（与 tier_planner 同时）。

## 输入（scout 在 task 字符串里传入）

- `session_dir`

## 步骤

1. 读 `<session_dir>/baseline.json` 的 `metrics` 字段（Wave 2 已写完，包含所有 metric 名字 + 值）

2. 按常识表判定方向（**不允许 unknown**；NAS run 模式无 ask_user，必须给出方向）：

   | 关键字（包含即匹配，case-insensitive） | 方向 |
   |---|---|
   | acc / accuracy / bleu / rouge / snr / psnr / auc / f1 / mAP / precision / recall / iou | `higher` |
   | loss / perplexity / wer / cer / epe / rmse / mae / mse / error / err / cost | `lower` |
   | latency / params / flops / memory / footprint / size | `lower` |
   | **以上都不匹配** | **`higher`**（乐观默认；多数自定义 metric 是"越大越好"） |

3. 决定 `primary_metric`：
   - 默认 `"acc"`（如果存在）
   - 没 acc → 最像 accuracy 的（accuracy / f1 / auc / mAP）
   - 都没 → metrics 里的**第一个非 latency/params 的 metric**（避免选到资源类指标当 primary）
   - 实在没有 → metrics 里的第一个

4. 写 `<session_dir>/metrics.json`：
   ```json
   {
     "primary_metric": "<name>",
     "metrics": [{"name": <str>, "direction": "higher|lower"}, ...]
   }
   ```

## 返回 scout 的 summary

```json
{
  "status": "ok",
  "primary_metric": "<name>",
  "summary": "metrics: primary=<X>, N metrics"
}
```

## 注意

- **所有 metric 必须有方向（higher/lower）**；不允许 `unknown`，因为 NAS run 模式无 ask_user 兜底
- 实在判断不准的 metric → 用启发式表的"乐观默认"（higher）
- primary_metric 不要选 latency_ms / params（这些是资源约束，不是优化目标；优化目标应该是 acc/loss/bleu 这类质量指标）
- 把 metrics.json 写到 session_dir，不要写到 working_dir
