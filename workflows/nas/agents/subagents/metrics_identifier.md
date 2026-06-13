# metrics_identifier (scout sub_agent task spec)

> scout 的 Wave 3 sub_agent，isolation="none"。baseline.json 写完后并发 issue（与 tier_planner 同时）。

## 输入（scout 在 task 字符串里传入）

- `session_dir`

## 步骤

1. 读 `<session_dir>/baseline.json` 的 `metrics` 字段（Wave 2 已写完，包含所有 metric 名字 + 值）

2. 按常识表判定方向：

   | 关键字 | 方向 |
   |---|---|
   | acc / accuracy / bleu / rouge / snr / psnr / auc / f1 / mAP | `higher` |
   | loss / perplexity / wer / cer / epe / rmse / mae / mse | `lower` |
   | latency / latency_ms / params / flops / memory | `lower` |
   | 其他 | `unknown` |

3. 决定 `primary_metric`：
   - 默认 `"acc"`
   - 没 acc → 最像 accuracy 的（accuracy / f1 / auc）
   - 都没 → metrics 里的第一个

4. 写 `<session_dir>/metrics.json`：
   ```json
   {
     "primary_metric": "<name>",
     "metrics": [{"name": <str>, "direction": "higher|lower|unknown"}, ...]
   }
   ```

## 返回 scout 的 summary

```json
{
  "status": "ok",
  "primary_metric": "<name>",
  "unknown_count": <int>,
  "summary": "metrics: primary=<X>, N metrics, M unknown"
}
```

## 注意

- 不确定的 metric 标 `"unknown"` —— scout 看到 unknown 会调 `ask_user` 确认方向
- 不要瞎猜方向；不确定就标 unknown 让人类决定
- 把 metrics.json 写到 session_dir，不要写到 working_dir
