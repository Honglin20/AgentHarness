---
order: 2
color: violet
icon: Search
status: active
workflows:
  - name: nas
    description: 端到端 NAS（探测 → 基线 → 迭代搜索 → refine → 报告）
---

# 结构搜索 (NAS)

围绕用户已有的训练项目，自动探测入口、生成 adapter、建立基线，然后以开放式 hypothesis + 多维 fitness 在精度/延迟/参数量之间迭代搜索结构改造方案，最后通过 tier 升级复跑确认并产出可部署推荐与架构优化建议。
