# MD 驱动方案：目录即元数据 + 解析规则

## 核心原则

- 目录结构 = 元数据（domain、level、order）
- MD 正文内容 = 渲染内容
- frontmatter 最小化（只写必要的 workflow 路径和标题）
- 一个解析脚本扫描目录，输出前端可消费的 JSON

---

## 目录结构

```
tutorials/
├── quantization/
│   ├── _index.md                 # 领域元数据（颜色、icon）
│   ├── 01_quick_start.md         # Level 1 教程
│   ├── 02_diagnostic.md          # Level 2 教程
│   ├── 03_full_chain.md          # Level 3 教程
│   └── api/
│       ├── quantizer.md          # API 文档
│       ├── study_runner.md
│       └── adapter.md
├── nas/
│   ├── _index.md
│   └── 01_simple_search.md
└── distillation/
    └── _index.md                 # 只有 index = coming soon
```

---

## 文件命名规则

| 信息 | 来源 | 示例 |
|------|------|------|
| domain | 文件夹名 | `quantization` |
| level | 文件名数字前缀 | `01` = Level 1 |
| order | 文件名数字前缀排序 | `01` < `02` < `03` |
| 标题 | frontmatter.title 或第一个 H1 | `基础量化` |

---

## MD 解析语法

### _index.md（领域元数据）

唯一需要 frontmatter 的文件：

```markdown
---
color: blue
icon: Layers
status: active              # active | coming_soon
---

# 模型量化

将 FP32 模型转换为低比特表示，在保持精度的同时降低推理开销。
```

### 教程 MD（正文）

```markdown
---
workflow: workflows/tutorials/mxint-analysis    # workflow 完整路径
title: 基础量化                                  # 可选，覆盖默认值
---

# 基础量化

5 分钟体验量化流程，自动分析模型、运行量化、对比精度。

## 分析项目结构 @analyzer

第一个 Agent 扫描你的项目目录，自动找到模型定义、数据集、权重文件。

### 使用工具

- **grep** — 搜索 `nn.Module` 子类定义
- **glob** — 查找 `.pt` / `.pth` 权重文件

### 输出结构

| 字段 | 说明 |
|------|------|
| model_class | nn.Module 类名 |
| dataset | 数据集名称 |
| weights_path | 权重文件路径 |

## 配置量化参数 @configurator

根据分析结果，Agent 生成量化配置...

## 执行量化脚本 @runner

Agent 运行量化脚本，对比 FP32 和量化模型精度...

## 保存诊断数据 @diagnostic_saver

将中间结果持久化为 JSON...

## 生成报告 @report_painter

最后一个 Agent 生成可视化报告...
```

### 解析规则

1. `## 标题 @agent_name` = 章节标题 + 对应的 DAG agent 节点
2. 两个 `##` 之间的内容 = 该章节的正文
3. `##` 后无 `@` = 章节标题，但不关联特定 agent（纯文本章节）
4. frontmatter 的 `workflow` 字段 = workflow 完整路径（相对于项目根目录）

---

## Workflow 目录约定

```
workflows/
├── _shared/
│   └── ...                        # 框架级共享
├── quantization/                  # 生产级 workflow
│   └── precision-diagnostic/
├── nas/                           # 生产级 workflow
│   └── nas-multi-obj/
└── tutorials/                     # 教学级 workflow
    ├── mxint-analysis/            # Level 1
    ├── mxint-diagnostic/          # Level 2
    └── precision-diagnostic/      # Level 3（教学版）
```

- 教学级 workflow → `workflows/tutorials/` 下
- 生产级 workflow → `workflows/<domain>/` 下
- 区分方式：目录位置，不需要修改 workflow.json

---

## API 文档

放在领域目录下的 `api/` 子目录：

```markdown
# Quantizer

将 FP32 模型量化为指定比特宽度。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| w_bits | int | 8 | 权重比特数 |
| a_bits | int | 8 | 激活比特数 |

## 示例

​```python
from bitx import Quantizer
q = Quantizer(w_bits=4, a_bits=4)
result = q.quantize(model, calib_loader)
​```

## 输出

返回 `QuantizeResult`，包含 accuracy、per_layer_qsnr 等字段。
```

未来 Chat 知识库索引 `tutorials/**/*.md`，API 文档自然在其中。

---

## 脚本输出

解析脚本把 MD 目录变成前端可消费的 JSON：

```json
{
  "domains": [
    {
      "id": "quantization",
      "title": "模型量化",
      "description": "将 FP32 模型转换为低比特表示...",
      "color": "blue",
      "icon": "Layers",
      "status": "active",
      "tutorials": [
        {
          "id": "quick_start",
          "level": 1,
          "title": "基础量化",
          "workflow": "workflows/tutorials/mxint-analysis",
          "sections": [
            { "title": "分析项目结构", "agent": "analyzer" },
            { "title": "配置量化参数", "agent": "configurator" },
            { "title": "执行量化脚本", "agent": "runner" },
            { "title": "保存诊断数据", "agent": "diagnostic_saver" },
            { "title": "生成报告", "agent": "report_painter" }
          ]
        }
      ],
      "apis": [
        { "id": "quantizer", "title": "Quantizer", "file": "tutorials/quantization/api/quantizer.md" },
        { "id": "study_runner", "title": "StudyRunner", "file": "tutorials/quantization/api/study_runner.md" },
        { "id": "adapter", "title": "Adapter", "file": "tutorials/quantization/api/adapter.md" }
      ]
    }
  ]
}
```
