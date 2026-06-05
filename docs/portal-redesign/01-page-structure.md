# 领域门户页面设计

## 整体导航流

```
                Page 1: 领域门户首页
                (替换当前落地页 CenterPanel.tsx idle state)
                 ┌──────┼──────┐
                 │             │
           [学习]             [工作流]
                 │             │
                 ▼             ▼
         Page 2: 教学页    Page 3: 生产工作流页
         · 进阶教程卡片     · 领域分区卡片网格
         · [试一试]→运行   · 点卡片→DAG+输入task→运行
```

三个页面共用的行为：任何运行动作最终都走同一套 `setSelectedTemplate` → DAG 预览 → ChatInput → `startWorkflow`。

---

## Page 1: 领域门户首页

替换当前 `CenterPanel.tsx` 中 `isIdle && !selectedTemplate` 的落地页。

```
┌──────────────────────────────────────────────────────────────────┐
│                         Logo                                     │
│                                                                  │
│               轻量化工具箱                                        │
│               选择一个领域开始                                     │
│                                                                  │
│   ┌─────────────────────┐  ┌─────────────────────┐              │
│   │  ██ 模型量化 ██      │  │  ██ 结构搜索 ██      │              │
│   │  blue gradient top   │  │  violet gradient top │              │
│   │                     │  │                     │              │
│   │  FP32 → 低比特      │  │  搜索最优网络结构    │              │
│   │  精度无损压缩        │  │  多目标优化          │              │
│   │                     │  │                     │              │
│   │  3 教程 · 3 工作流  │  │  2 教程 · 2 工作流   │              │
│   │                     │  │                     │              │
│   │  [学习]  [工作流]   │  │  [学习]  [工作流]    │              │
│   └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
│   ┌─────────────────────┐  ┌─────────────────────┐              │
│   │  ██ 知识蒸馏 ██      │  │  ██ 模型剪枝 ██      │              │
│   │  amber, grayed      │  │  rose, grayed        │              │
│   │                     │  │                     │              │
│   │  即将推出            │  │  即将推出            │              │
│   │       [🔒 coming]   │  │       [🔒 coming]   │              │
│   └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

颜色方案：
- 量化: `blue` gradient `from-blue-500 to-cyan-400`
- NAS: `violet` gradient `from-violet-500 to-purple-400`
- 蒸馏: `amber` gradient `from-amber-500 to-orange-400`
- 剪枝: `rose` gradient `from-rose-500 to-pink-400`

---

## Page 2: 教学页

从门户"学习"按钮进入。详见 `02-tutorial-page.md`。

---

## Page 3: 生产工作流页

从门户"工作流"按钮进入。

```
┌──────────────────────────────────────────────────────────────────┐
│ ← 返回门户         轻量化工作流                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ━━ 模型量化 ────────────────────────────────────────────────    │  blue left border
│                                                                  │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ │
│  │ mxint-analysis   │ │ precision-       │ │ quant-           │ │
│  │                  │ │ diagnostic       │ │ benchmark        │ │
│  │ 基础量化分析     │ │ 格式无关诊断链   │ │ 量化精度基准评测 │ │
│  │ 5 agents         │ │ 7 agents         │ │ 4 agents         │ │
│  │ analyzer → ...   │ │ adapter → ...    │ │ runner → ...     │ │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘ │
│                                                                  │
│  ━━ 结构搜索 (NAS) ──────────────────────────────────────────    │  violet left border
│                                                                  │
│  ┌──────────────────┐ ┌──────────────────┐                       │
│  │ nas-multi-obj    │ │ nas-proxy        │                       │
│  │ 多目标NAS优化    │ │ Proxy-based NAS  │                       │
│  └──────────────────┘ └──────────────────┘                       │
│                                                                  │
│  ━━ 知识蒸馏 ───────────────────── coming soon                   │  amber, dashed
│  ━━ 模型剪枝 ───────────────────── coming soon                   │  rose, dashed
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

交互：点卡片 → 选中 workflow → DAG 预览 + ChatInput → 运行。

---

## 数据模型

所有页面由 `docs/domains/<name>/manifest.yaml` 驱动。

```yaml
# docs/domains/quantization/manifest.yaml
domain: quantization
title: 模型量化
color: blue
icon: Layers
status: active              # active | coming_soon
description: 将 FP32 模型转换为低比特表示...

# 教学页用
tutorials:
  - id: basic_quant
    title: 基础量化
    level: 1
    description: 5 分钟体验量化流程
    learning_points: [...]
    workflow: mxint-analysis
    content: tutorials/01_basic_quant.md
  - id: diagnostic
    title: 精度诊断
    level: 2
    workflow: mxint-diagnostic
    content: tutorials/02_diagnostic.md
  - id: full_chain
    title: 通用诊断链
    level: 3
    workflow: precision-diagnostic
    content: tutorials/03_full_chain.md

# 生产工作流页用（独立列表，不含教学 workflow）
workflows:
  - name: mxint-analysis
    description: 基础量化分析
    agents_count: 5
    dag_summary: analyzer → configurator → runner → ...
  - name: precision-diagnostic
    description: 格式无关诊断链
    agents_count: 7
    dag_summary: adapter → quant_study → ...
```

新增领域 = 新建 manifest 文件，前端零改动。
