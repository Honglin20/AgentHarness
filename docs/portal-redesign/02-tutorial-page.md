# 教学页设计：章节导航与 DAG 合并

## 核心理念

左侧面板中，**章节导航和 DAG 是同一个东西**。每个节点既是 DAG 的 agent 节点，也是章节入口。

每个教学 Level 关联一个 workflow，不同 Level 的 DAG 拓扑不同。

---

## 整体布局

以 Example 18（mxint-analysis，5 agents 串行）为例：

```
┌──────────────────────────────────────────────────────────────────┐
│ ← 返回门户        ● 量化 · 基础量化                             │  blue accent
│                  [① 基础量化]  [② 精度诊断]  [③ 通用诊断链]      │  Level tabs
├──────────────────┬───────────────────────────────────────────────┤
│                  │                                               │
│  ● 分析项目结构   │  # 1. 分析项目结构                            │
│  │  analyzer     │                                               │
│  │               │  第一个 Agent 扫描你的项目目录，自动找到：      │
│  ▼               │  - 模型类名（如 ResNet18）和模块路径           │
│  ● 配置量化参数   │  - 数据集名称                                │
│  │  configurator │  - 权重文件路径                              │
│  │               │                                               │
│  ▼               │  ### 使用工具                                │
│  ● 执行量化脚本   │                                               │
│  │  runner       │  **grep** — 搜索 nn.Module 子类定义          │
│  │               │  **glob** — 查找 .pt/.pth 权重文件           │
│  ▼               │                                               │
│  ● 保存诊断数据   │  ### 输出                                    │
│  │  diag_saver   │                                               │
│  │               │  | 字段 | 说明 |                              │
│  ▼               │  | model_class | nn.Module 类名 |             │
│  ● 生成报告       │  | dataset | 数据集名称 |                    │
│     report_painter│  | weights_path | 权重文件路径 |             │
│                  │                                               │
│  ─────────────── │                                               │
│  [试一试 ▶]       │                                               │
│                  │                                               │
├──────────────────┴───────────────────────────────────────────────┤
└──────────────────────────────────────────────────────────────────┘
```

---

## 左侧节点设计

每个节点 = DAG 节点 + 章节入口：
- **圆点 + 竖线** = DAG 拓扑（串行竖线，分叉画分叉，汇聚画汇聚）
- **第一行粗体** = 章节名（如"分析项目结构"）
- **第二行小字** = agent 名（如 `analyzer`）
- **点击节点** → 右侧正文滚动到对应章节
- **滚动正文** → 左侧当前章节节点自动高亮

### 节点样式状态

```
当前阅读    ●━━━  分析项目结构        (蓝色实心 + 蓝色连线 + 蓝色文字)
              ┃   analyzer

已完成      ✓━━━  项目适配            (绿色勾 + 灰色连线 + 灰色文字)
              ┃   adapter

未到达      ○┄┄┄  执行量化脚本        (灰色空心 + 虚线 + 浅灰文字)
              ┃   runner
```

---

## 分叉 DAG 示例（Example 19，10 agents）

```
┌──────────────────┬───────────────────────────────────────────────┐
│                  │                                               │
│  ● 项目适配      │  # 1. 项目适配                                │
│  │  adapter      │  ...                                         │
│  ▼               │                                               │
│  ● 运行量化实验   │  # 2. 运行量化实验                            │
│  │  study_runner │  ...                                         │
│  ┼───────────────│                                               │
│  │       │       │                                               │
│  ▼       ▼       │                                               │
│  ● 差距  ● 层归因 │  # 3. 精度差距分析 / # 4. 层级归因           │
│  │       │       │                                               │
│  │  ┼────┼────┼  │                                               │
│  │  ▼    ▼    ▼  │                                               │
│  │  ●分布 ●Block ●干预                                           │
│  │  │    │    │  │  # 5/6/7. 分布画像 / Block分析 / 干预策略     │
│  │  └────┼────┘  │                                               │
│  │       ▼       │                                               │
│  │  ● 综合报告    │  # 8. 综合报告                                │
│  │     synthesis  │                                               │
│  │       ▼       │                                               │
│  │  ● 保存诊断    │  # 9. 保存诊断数据                            │
│  │     diag_saver │                                               │
│  │       ▼       │                                               │
│  └─ ● 生成报告    │  # 10. 生成可视化报告                         │
│     report_painter│                                               │
│                  │                                               │
│  ─────────────── │                                               │
│  [试一试 ▶]       │                                               │
└──────────────────┴───────────────────────────────────────────────┘
```

分叉结构清晰可见：
- `study_runner` 后分成 `gap_analyzer` 和 `layer_attribution`
- `layer_attribution` 再分三路：`distribution_profiler`、`block_analyst`、`intervention_evaluator`
- 三路汇聚到 `synthesis`
- 之后串行到 `diagnostic_saver` → `report_painter`

---

## 多 Level 切换

同一领域有多个 Level，顶部 tab 切换：

```
[① 基础量化]  [② 精度诊断]  [③ 通用诊断链]
```

切换 Level → 左侧 DAG 变为对应 workflow 的 DAG，右侧正文切换为对应教程。
每个 Level 的 DAG 拓扑完全不同。

---

## 数据结构

DAG 拓扑从 `workflow.json` 读取（已有 `dag.nodes` + `dag.edges`），
sections 只需给每个 agent 节点追加章节标题和教程文件路径：

```yaml
# manifest.yaml
tutorials:
  - id: basic_quant
    title: 基础量化
    level: 1
    workflow: mxint-analysis
    sections:
      - title: 分析项目结构
        agent: analyzer
        file: tutorials/01_basic_quant/01_analyzer.md
      - title: 配置量化参数
        agent: configurator
        file: tutorials/01_basic_quant/02_configurator.md
      - title: 执行量化脚本
        agent: runner
        file: tutorials/01_basic_quant/03_runner.md
      - title: 保存诊断数据
        agent: diagnostic_saver
        file: tutorials/01_basic_quant/04_diagnostic_saver.md
      - title: 生成报告
        agent: report_painter
        file: tutorials/01_basic_quant/05_report_painter.md
```

前端合并 workflow.json 的 DAG 数据和 manifest 的 sections 数据渲染。
