---
order: 2
color: violet
icon: Search
status: active
workflows:
  - name: simple-nas
    description: 精简版 NAS（6 agent 串行：探测 → 基线 → 变异搜索 → 报告）
  - name: nas
    description: 完整版 NAS（15 agent：5 并行 setup + scout 汇聚 → 迭代搜索 → tier 升级 → 报告）
---

# 结构搜索 (NAS)

围绕用户已有的训练项目（任意框架，只要能 `import` 出 `nn.Module`），自动探测入口、生成 adapter、建立基线，然后以开放式 hypothesis + 多维 fitness 在精度/延迟/参数量之间迭代搜索结构改造方案，最后通过 tier 升级复跑确认并产出可部署推荐与架构优化建议。

提供两个工作流：
- **SIMPLE NAS**（`simple-nas`）：6 个 agent 串行，快速跑通整条链路，适合学习和小项目。
- **NAS WORKFLOW**（`nas`）：15 个 agent，5 节点并行 setup + 多维 fitness + tier 渐进升级，适合生产级搜索。
