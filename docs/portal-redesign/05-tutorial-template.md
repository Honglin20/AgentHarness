# 教程正文写作模板

## 模板结构

一个教程 MD 由三部分组成：**头部 frontmatter**、**章节正文**、**可选的收尾总结**。

```markdown
---
workflow: workflows/tutorials/{workflow_name}
title: {教程标题}
---

# {教程标题}

{一段话概括：这个教程做什么、结束时用户得到什么}

## {章节标题} @{agent_name}

{1-2 句话说明这个 Agent 在整体流程中的角色}

### 使用工具

{列出 Agent 使用的工具，每个一句话说明}

- **tool_name** — 做什么

### 输出

{描述 result_type 的关键字段，用表格}

| 字段 | 说明 |
|------|------|
| field | 含义 |

---

## {下一章节} @{next_agent}

...

---

## 总结

{回顾整个 workflow 做了什么，最终产出是什么}
```

---

## 规则

| 规则 | 必要性 | 说明 |
|------|--------|------|
| `## 标题 @agent` | 必须 | 章节入口 + DAG 节点映射 |
| `### 使用工具` | 推荐 | 列出 Agent 使用的工具 |
| `### 输出` | 推荐 | 用表格描述 result_type 关键字段 |
| 段落正文 | 必须 | 章节开头 1-2 句说明角色，其余自然叙述 |
| `## 总结` | 可选 | 教程末尾回顾流程 |
| API 链接 | 可选 | 正文自然出现时写 `[名称](api/xxx.md)` |
| `---` | 推荐 | 章节之间用分隔线 |

不强制每个章节都按同一结构写——如果某个 Agent 很简单，一两句话就够了。

---

## 完整示例：01_quick_start.md

```markdown
---
workflow: workflows/tutorials/mxint-analysis
title: 基础量化
---

# 基础量化

5 分钟完成一次模型量化分析。你会看到框架如何自动分析项目、配置参数、
运行量化，最终生成一份包含精度对比和层级别 QSNR 的可视化报告。

## 分析项目结构 @analyzer

第一个 Agent 扫描项目目录，自动找到模型定义、数据集和权重文件。
你不需要手动指定任何参数。

### 使用工具

- **grep** — 搜索 `nn.Module` 子类定义，定位模型类名
- **glob** — 查找 `.pt` / `.pth` 权重文件和已有适配器
- **bash** — 执行快速验证脚本

### 输出

Agent 输出结构化的 `ProjectAnalysis`，供下游 Agent 直接消费：

| 字段 | 说明 |
|------|------|
| model_class | 模型类名，如 `ResNet18` |
| model_module | 模块导入路径，如 `models.resnet` |
| dataset | 数据集名称，如 `CIFAR-10` |
| weights_path | 权重文件路径 |
| weights_exist | 权重文件是否存在 |

## 配置量化参数 @configurator

根据 analyzer 的结果，这个 Agent 生成量化适配器和运行配置。
如果某些信息无法自动检测（比如自定义数据集），它会通过 **ask_user** 向你提问。

### 使用工具

- **ask_user** — 向用户确认量化位数等关键参数
- **write_file** — 写入适配器代码
- **bash** — 验证适配器是否可导入

### 输出

| 字段 | 说明 |
|------|------|
| adapter_path | 适配器文件路径 |
| cli_command | 完整的量化运行命令 |
| w_bits / a_bits | 权重/激活比特数 |
| block_size | 分块量化粒度 |

## 执行量化脚本 @runner

Agent 执行 configurator 生成的命令，运行量化脚本，
对比 FP32 和量化模型的精度，记录每层 QSNR。

### 使用工具

- **bash** — 执行量化脚本，捕获输出

### 输出

| 字段 | 说明 |
|------|------|
| status | 运行状态：success / error |
| fp32_accuracy | FP32 基线精度 |
| quant_accuracy | 量化后精度 |
| accuracy_delta | 精度差值 |
| worst_layer | QSNR 最差的层 |
| worst_qsnr_db | 最差层的 QSNR 值 |

## 保存诊断数据 @diagnostic_saver

将量化过程中产生的中间数据持久化为 JSON，供后续分析和报告使用。

### 使用工具

- **bash** — 写入诊断 JSON 文件

### 输出

| 字段 | 说明 |
|------|------|
| diagnostic_dir | 诊断数据目录路径 |
| status | 保存状态 |

## 生成报告 @report_painter

最后一个 Agent 读取诊断数据，生成包含图表的可视化报告。
使用 **render_chart** 绘制精度对比柱状图、QSNR 分布图等。

### 使用工具

- **render_chart** — 绘制可视化图表
- **read_text_file** — 读取诊断数据
- **bash** — 辅助数据处理

### 输出

自由格式的学术分析报告，包含内嵌图表。

---

## 总结

整个 workflow 从分析到报告全自动完成：

1. **analyzer** 自动发现项目结构
2. **configurator** 生成量化配置
3. **runner** 执行量化并记录精度
4. **diagnostic_saver** 持久化中间数据
5. **report_painter** 生成可视化报告

[试一试这个 Workflow ▶]
```
