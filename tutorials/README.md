# Tutorials 内容编写指南

本文档说明如何编写领域教程和 API 文档，以及它们在前端的渲染方式。

---

## 目录结构

```
tutorials/
├── <domain>/                  # 一个领域 = 一个目录
│   ├── _index.md              # 领域入口（必须）
│   ├── 01_quick_start.md      # Level 1 教程
│   ├── 02_intermediate.md     # Level 2 教程
│   ├── 03_advanced.md         # Level 3 教程
│   ├── api/                   # API 文档目录
│   │   ├── tool_a.md
│   │   └── tool_b.md
│   └── examples/              # 示例项目（可选，不影响解析）
└── README.md                  # 本文件
```

对应的工作流放在 `workflows/` 目录下：

```
workflows/
├── <workflow-name>/
│   └── workflow.json          # Agent 定义 + DAG 拓扑
```

---

## 1. 领域入口: `_index.md`

每个领域目录下**必须**有 `_index.md`，它是领域卡片的唯一数据源。

### frontmatter 字段

```yaml
---
order: 1                      # 排序权重，数字越小越靠前
color: blue                   # 主题色: blue / violet / amber / rose
icon: Layers                  # 图标: Layers / Search / Flame / Scissors
status: active                # active | coming_soon
workflows:                    # 生产工作流列表（门户"工作流"页展示）
  - name: mxint-analysis      # workflows/ 下的目录名
    description: 基础量化分析  # 卡片描述
---
```

### 正文

```markdown
# 模型量化

将 FP32 模型转换为低比特表示，在保持精度的同时降低推理开销。
```

- `# 标题` → 领域卡片标题
- 标题后第一段非空文本 → 领域描述

### 前端渲染位置

| 字段 | 渲染位置 |
|------|---------|
| title | 门户首页领域卡片标题、教学页面包屑、API 页面包屑 |
| description | 门户首页领域卡片描述 |
| color | 领域卡片左边框颜色、教程页 Level tab 颜色、API 页色点 |
| icon | 领域卡片图标（Layers/Search/Flame/Scissors） |
| status=active | 显示教程卡片 + "工作流 →" 链接 |
| status=coming_soon | 显示灰色虚线框 + 🔒 "即将推出" |
| order | 控制门户首页从上到下的排列顺序 |
| workflows | 门户"工作流"页展示的卡片列表 |

---

## 2. 教程: `01_xxx.md` / `02_xxx.md` / `03_xxx.md`

### 文件命名规则

- **前缀数字决定 Level**：`01_` → Level 1，`02_` → Level 2，`03_` → Level 3
- 前缀数字后面的部分去掉 `_-` 后作为教程 ID
- 示例：`01_quick_start.md` → level=1, id=`quick_start`

### frontmatter 字段

```yaml
---
workflow: mxint-analysis       # 关联的 workflow 名（workflows/ 下的目录名）
title: 基础量化                # 教程标题（不设则从正文 # H1 提取）
badge: Quick Start             # 可选，徽章文字（如 Quick Start）
apis: [quantizer]              # 可选，兜底 API 列表（通常不需要，正文链接自动提取）
---
```

- `workflow` 有两个用途：
  1. 教学页左下角「试一试」按钮点击后，加载这个 workflow 的 DAG 并进入运行模式
  2. 后端从这个 workflow 的 `workflow.json` 读取 DAG 拓扑，用于左侧 DAG 导航

### 正文结构

```markdown
# 教程标题

一段话描述这个教程做什么、用户能学到什么。

## 章节标题 @agent_name

章节正文，支持完整 Markdown（标题、列表、表格、代码块等）。

可以引用 API：[Quantizer](api/quantizer.md)  ← 这个链接会被自动提取

## 另一个章节 @another_agent

...

---

## 总结

总结段落。
```

### 关键规则

#### `## 章节标题 @agent_name` 语法

- `##` 开头 = 一个章节
- `@agent_name` 是可选的，绑定到 workflow 中的 agent
- **agent 名必须和 `workflow.json` 中的 agent `name` 一一对应**
- 没有带 `@` 的 `##` 不绑定 agent（如 `## 总结`）

#### API 引用链接

正文中写 `[显示文字](api/xxx.md)` 会自动识别为 API 引用：

```markdown
调用 [Quantizer](api/quantizer.md) 进行量化
```

解析规则：
- 只匹配 `api/` 开头的链接路径
- 文件名去掉 `.md` 后缀作为 API ID
- 自动去重，保留出现顺序
- 每个章节独立提取 `api_refs` 列表

#### 章节边界

- 章节内容 = 从 `##` 下一行到下一个 `##` 之前
- 最后一个章节末尾的 `---` 分隔线会被自动裁剪
- 正文 `# H1` 到第一个 `##` 之间的内容不属于任何章节（教程描述区）

### 前端渲染位置

| 数据 | 渲染位置 |
|------|---------|
| title + badge | 门户首页教程卡片 |
| description (H1 后第一段) | 教程卡片描述文字 |
| level | 门户首页教程卡片 badge、教学页 Level tab |
| sections[] | 教学页中间栏，每个章节渲染为一段 Markdown |
| section.title | 左侧 DAG 导航中的节点标题 |
| section.agent | 左侧 DAG 导航中的节点标签（`@agent`） |
| section.api_refs | 右侧面板：当前章节引用的 API 卡片高亮（蓝色边框） |
| workflow | DAG 拓扑来源（从 workflow.json 读取）、「试一试」按钮关联 |

---

## 3. API 文档: `api/xxx.md`

### 文件命名

- 文件名（去掉 `.md`）= API ID
- 必须在 `api/` 子目录下才会被识别为 API 文档

### 正文结构

```markdown
# API 名

一句话描述这个 API 做什么。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| param_a | int | 8 | 参数说明 |
| param_b | str | "auto" | 参数说明 |

## 示例

​```python
from xxx import APIName
result = APIName(param_a=4)
print(result.field)
​```

## 输出

返回 `ResultType`，包含：

| 字段 | 说明 |
|------|------|
| field1 | 说明 |
| field2 | 说明 |
```

### 关键规则

- `# H1` 标题 = API 标题（渲染到左侧导航和页面标题）
- H1 后第一段非空文本 = API 描述（渲染到教学页右侧 API 卡片）
- 正文支持完整 Markdown（表格、代码块等）
- 建议包含 `参数`、`示例`、`输出` 三个标准章节

### 反向映射（自动生成）

解析脚本自动建立 API → 教程的反向映射：

```
教程正文写了 [Quantizer](api/quantizer.md)
  ↓ 自动提取
section.api_refs = ["quantizer"]
  ↓ 汇总
API quantizer.referenced_by = [{tutorial: "quick_start", section: "执行量化脚本"}]
```

这个反向映射渲染在 API 文档页左侧导航的"相关教程"区域。

### 前端渲染位置

| 数据 | 渲染位置 |
|------|---------|
| title + description | 教学页右侧 API 卡片（所有 API 始终显示） |
| 当前章节引用的 API | 右侧卡片高亮（蓝色边框+蓝色文字） |
| markdown 全文 | API 文档页右侧内容区 |
| referenced_by | API 文档页左侧导航"相关教程"区域 |
| other_apis | API 文档页左侧导航"API 参考"列表 |

---

## 4. Workflow: `workflows/<name>/workflow.json`

### 结构

```json
{
  "name": "workflow-name",
  "agents": [
    { "name": "agent_a", "description": "做什么事", "after": [] },
    { "name": "agent_b", "description": "做什么事", "after": ["agent_a"] },
    { "name": "agent_c", "description": "做什么事", "after": ["agent_b"] }
  ]
}
```

### 关键规则

- **agent `name` 必须和教程 `## 标题 @name` 中的 `@name` 严格一致**
- `after` 数组定义 DAG 边（依赖关系）
- `description` 显示在工作流页卡片上
- 支持 `on_pass` / `on_fail` 条件边（可选）

### 和教程的关联

```
教程 frontmatter:  workflow: mxint-analysis
                          ↓
workflows/mxint-analysis/workflow.json 中的 agents
                          ↓
教程正文的 ## 章节 @agent_name 必须和 agents[].name 对应
```

### 前端渲染位置

| 数据 | 渲染位置 |
|------|---------|
| agents[].name | DAG 导航中的节点 |
| agents[].description | 工作流页卡片的 agent 数量信息 |
| DAG edges | DAG 预览的连线 |
| 整个 workflow | 「试一试」按钮或工作流页卡片点击后进入 DAG 预览 |

---

## 5. 端到端流程：新增一个领域

### 最小可运行（coming soon）

```
tutorials/
└── new_domain/
    └── _index.md          # status: coming_soon
```

门户首页出现灰色卡片，无教程、无工作流。

### 完整领域

1. **创建目录**

```
tutorials/new_domain/
├── _index.md
├── 01_tutorial.md
├── 02_tutorial.md
└── api/
    └── tool.md
```

2. **写 `_index.md`** — 设 order, color, icon, status=active, workflows 列表

3. **写教程 MD** — 每个章节用 `## 标题 @agent_name`，正文可引用 `[Tool](api/tool.md)`

4. **写 API 文档** — 标准 `参数/示例/输出` 结构

5. **创建 workflow**

```
workflows/new_workflow/
└── workflow.json           # agents[].name 对应教程 @agent
```

6. **刷新** — 重启服务器或调用 `POST /api/domains/refresh`

### 验证

```bash
# 查看解析结果
python -c "from server.tutorial_parser import parse_tutorials; import json; json.dump(parse_tutorials(), sys.stdout, indent=2, ensure_ascii=False)"

# 检查 API 响应
curl -s http://localhost:8000/api/domains | python3 -m json.tool

# 检查教程详情
curl -s http://localhost:8000/api/domains/<domain>/tutorials/<id> | python3 -m json.tool

# 检查 API 文档
curl -s http://localhost:8000/api/domains/<domain>/api/<name> | python3 -m json.tool
```

---

## 6. 前端页面一览

### 门户首页 (`DomainPortal`)

```
┌──────────────────────────────────────────────┐
│                   Logo                       │
│                                              │
│  ┌──────────┐  ┌──────────┐                 │
│  │ 量化      │  │ NAS      │  ← order 排序   │
│  │ blue      │  │ violet   │                 │
│  │ [教程卡片] │  │ [教程卡片] │                 │
│  │ [工作流→] │  │ [工作流→] │                 │
│  └──────────┘  └──────────┘                 │
│  ┌──────────┐  ┌──────────┐                 │
│  │ 蒸馏 🔒   │  │ 剪枝 🔒   │  ← coming_soon │
│  │ amber     │  │ rose     │                 │
│  └──────────┘  └──────────┘                 │
└──────────────────────────────────────────────┘
```

- 每个领域一个卡片区域
- 教程卡片点击 → 教学页
- "工作流 →" 点击 → 生产工作流页

### 教学页 (`DomainTutorialPage`)

```
┌──────────────────────────────────────────────┐
│ ← 返回 / 量化 / 基础量化        [1][2][3]    │
├──────┬────────────────────┬─────────────────┤
│ DAG  │  ## 章节1 @agent1  │ API 参考        │
│ 导航 │  正文...           │ ┌─────────────┐ │
│      │                    │ │ Tool A ←高亮│ │
│  ●   │  ## 章节2 @agent2  │ └─────────────┘ │
│  │   │  正文...           │ ┌─────────────┐ │
│  ▼   │                    │ │ Tool B      │ │
│  ●   │                    │ └─────────────┘ │
│      │                    │                 │
│ ──── │                    │                 │
│ [试一│                    │                 │
│  试] │                    │                 │
└──────┴────────────────────┴─────────────────┘
```

- 左侧：DAG 章节导航 + 「试一试」
- 中间：Markdown 正文，IntersectionObserver 联动左侧高亮
- 右侧：所有 API 卡片始终显示，当前章节引用的高亮

### API 文档页 (`ApiDocPage`)

```
┌──────────────────────────────────────────────┐
│ ← 返回 / 量化 / Quantizer                    │
├──────────┬───────────────────────────────────┤
│ API 参考 │  # Quantizer                      │
│          │  将 FP32 模型量化...               │
│ ● Quant │                                    │
│   StudyR │  ## 参数                           │
│          │  | 参数 | 类型 | ...               │
│ 相关教程 │                                    │
│ · 基础量化│  ## 示例                           │
│   →执行  │  ```python ...```                  │
│          │                                    │
│          │  ## 输出                           │
│          │  ...                               │
└──────────┴───────────────────────────────────┘
```

- 左侧：API 列表（当前高亮）+ 相关教程（反向映射）
- 右侧：全宽 Markdown 渲染

---

## 7. 注意事项

### 文件编码
所有 MD 文件必须 UTF-8 编码。

### 章节标题中的 `@agent`
- `@` 后只允许 `\w+`（字母、数字、下划线）
- `@` 必须紧跟在章节标题末尾
- 正确：`## 执行量化 @runner`
- 错误：`## 执行量化@runner`（`@` 前要有空格）
- 错误：`## 执行量化 @runner script`（`@` 后不能有空格直到行尾）

### API 链接格式
- 必须是 `api/` 开头的相对路径
- 正确：`[Quantizer](api/quantizer.md)`
- 正确：`[搜索空间](api/search_space.md)`
- 不会识别：`[外部链接](https://...)`、`[其他教程](../other.md)`

### Level 编号
- 文件名前缀 `01_` → Level 1, `02_` → Level 2, `03_` → Level 3
- Level 值用于排序和前端 Level tab 显示
- 建议每个领域 3 个 Level：基础 → 进阶 → 高级

### coming_soon 领域
- 只需要 `_index.md`，设 `status: coming_soon`
- 不需要教程 MD、API 文档、workflow
- 前端自动显示灰色虚线框 + 🔒

### 排序
- 领域间排序：`_index.md` 的 `order` 字段（数字越小越前）
- 教程间排序：文件名字母序（`01_` 天然排在 `02_` 前面）
- API 间排序：文件名字母序
