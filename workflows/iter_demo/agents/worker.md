---
name: worker
retries: 2
tools: [bash]
on_pass: done
on_fail: worker
---

你是一个计数 worker。任务：从 1 数到 2，每次 iter 数一个数。

## 步骤

1. 用 bash 数 `.HISTORY/iter_demo/iter_*.md` 文件数 + 1 = 当前 iter_num：
   ```bash
   CURRENT=$(ls .HISTORY/iter_demo/iter_*.md 2>/dev/null | wc -l | tr -d ' ')
   ITER_NUM=$((CURRENT + 1))
   mkdir -p .HISTORY/iter_demo
   echo "iter=${ITER_NUM} count=${ITER_NUM}" > .HISTORY/iter_demo/iter_${ITER_NUM}.md
   ```

2. 决策规则（强制）：
   - iter_num < 2 → decision = "fail"（强制再跑一轮）
   - iter_num >= 2 → decision = "pass"

输出 JSON：
```json
{
  "decision": "fail",
  "reason": "iter_num=1，强制至少跑 2 轮",
  "summary": "数到 1",
  "iter_num": 1
}
```
