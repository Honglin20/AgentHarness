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

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order` | 整数 | 否 | 排序权重，数字越小越靠前。默认 `99` |
| `color` | 字符串 | 否 | 领域主题色，控制标题左侧竖线、文字颜色。默认 `blue` |
| `icon` | 字符串 | 否 | 标题旁的图标。默认 `Layers` |
| `status` | 字符串 | 否 | `active`（默认）或 `coming_soon` |
| `workflows` | 列表 | 否 | 门户"工作流"页展示的卡片列表 |

**颜色可选值**：`blue`、`violet`、`amber`、`rose`

**图标可选值**：`Layers`、`Search`、`Flame`、`Scissors`

**status 两种状态**：
- `active`：正常展示所有教学卡片，"工作流 →" 链接可见
- `coming_soon`：标题仍显示，但卡片区域替换为灰色虚线框 + 🔒 提示。可提前准备内容，修改 status 即可上线

### 正文

```markdown
# 模型量化

将 FP32 模型转换为低比特表示，在保持精度的同时降低推理开销。
```

- `# 标题` → 领域卡片标题（同时出现在教学页面包屑、API 页面包屑）
- 标题后第一段非空文本 → 领域描述

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

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `workflow` | 字符串 | 否 | 关联的工作流。设置后出现 "Try it" 按钮，详见[第 4 节](#4-try-it连接工作流) |
| `title` | 字符串 | 推荐 | 教程标题。省略则从正文 H1 自动提取 |
| `badge` | 字符串 | 否 | 卡片角标文字。详见下方 |
| `apis` | 列表 | 否 | 手动声明的 API 引用。正文中的链接会自动提取并合并 |

#### Badge（卡片高亮）

设置 `badge` 后，Portal 首页的卡片会显示角标并改变颜色样式：

| badge 值 | 效果 |
|-----------|------|
| `Quick Start` | **绿色**边框和背景，绿色角标 + 终端图标 |
| 不设置 | 使用领域自身颜色，普通样式 |

**建议**：每个领域的第一个教程设置 `badge: Quick Start`，作为入门引导。

#### workflow 字段的作用

`workflow` 有两个用途：
1. 教学页右上角 "Try it" 按钮点击后，加载这个 workflow 进入运行模式
2. 后端从这个 workflow 的 `workflow.json` 读取 DAG 拓扑，用于左侧 MiniDag 导航

`workflow` 为空或不设置时，"Try it" 按钮不显示。

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

#### 教程描述（卡片副标题）

卡片副标题的提取优先级：
1. 正文 H1 之后的第一段非空文字（推荐写上一两句）
2. 若无描述文字，自动生成 `{agent 数量} agents · Level {level}`

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

#### 滚动联动

教学页左侧的章节导航会自动追踪右侧阅读位置：正在阅读哪个章节，左侧就高亮哪个条目。同时，左侧 MiniDag 会高亮当前章节对应的 agent 节点。点击左侧章节标题可平滑滚动到对应位置。

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

- `# H1` 标题 = API 标题（出现在左侧导航和页面标题）
- H1 后第一段非空文本 = API 描述（出现在教学页右侧 API 卡片）
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

---

## 4. Try it：连接工作流

### 匹配机制

教学页右上角的 "Try it" 按钮通过**名称匹配**连接到工作流：

```
Tutorial MD 的 workflow 字段  →  按 "/" 分割取最后一段  →  匹配已注册工作流的 name
```

**示例**：

| workflow 字段值 | 提取结果 | 匹配目标 |
|----------------|---------|---------|
| `workflows/tutorials/mxint-analysis` | `mxint-analysis` | 工作流 name = `mxint-analysis` |
| `mxint-analysis` | `mxint-analysis` | 工作流 name = `mxint-analysis` |
| `workflows/tutorials/sub/mxint-analysis` | `mxint-analysis` | 工作流 name = `mxint-analysis` |

以上三种写法等效。

### 匹配行为

| 情况 | 结果 |
|------|------|
| 匹配成功 | 点击 Try it → 加载工作流 DAG，进入运行视图 |
| 匹配失败（工作流未注册） | 点击 Try it → 无反应（静默失败） |
| workflow 未设置或为空 | Try it 按钮不显示 |

### 确保工作流可被发现

工作流必须已注册到系统中才能被 Try it 找到。确认 `workflows/<name>/workflow.json` 文件存在，且系统接口 `GET /api/workflows/definitions` 能返回该工作流的定义。

### MiniDag 展示

如果 Tutorial 关联了工作流，教学页左侧会显示工作流拓扑图（MiniDag）：

- **节点** = 工作流中的 agent（来自 `workflow.json` 的 `agents`）
- **连线** = agent 之间的依赖关系（`after` 字段）
- **高亮** = 当前阅读章节的 `@agent_name` 对应的节点会突出显示

拓扑图数据来源优先级：
1. `workflow.json` 中的 `dag` 字段（如果存在且非空）
2. 根据 agents 的 `after` / `on_pass` / `on_fail` 依赖自动计算

---

## 5. Workflow: `workflows/<name>/workflow.json`

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

---

## 6. 端到端流程：新增一个领域

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
# 查看解析结果（打印完整 JSON）
python -m server.tutorial_parser

# 检查 API 响应
curl -s http://localhost:8000/api/domains | python3 -m json.tool

# 检查教程详情（含 DAG 拓扑）
curl -s http://localhost:8000/api/domains/<domain>/tutorials/<id> | python3 -m json.tool

# 检查 API 文档
curl -s http://localhost:8000/api/domains/<domain>/api/<name> | python3 -m json.tool
```

---

## 7. 页面结构一览

### 门户首页

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

### 教学页

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

### API 文档页

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

## 8. 注意事项

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

---

## 9. 常见问题

### 创建了新的 Tutorial MD 文件，但 Portal 上没看到？

1. 确认文件在正确的领域目录下（`tutorials/{domain-id}/`）
2. 确认该目录下有 `_index.md`
3. 调用 `POST /api/domains/refresh` 刷新缓存
4. 刷新前端页面

### Try it 按钮没有显示？

Tutorial MD 的 frontmatter 中未设置 `workflow` 字段。添加即可：
```yaml
---
workflow: your-workflow-name
---
```

### Try it 按钮点了没反应？

1. 确认 `workflow` 字段的值（取 `/` 最后一段）能在 `GET /api/workflows/definitions` 返回的列表中找到
2. 确认对应工作流目录下存在 `workflow.json` 文件
3. 注意：当前版本匹配失败时**静默无反应**，不会提示错误

### API 文档中的反向引用没有显示？

- 确认教学章节中使用了正确的链接格式：`[文字](api/xxx.md)`
- 确认 `api/` 目录下的文件名与链接中的名称一致
- 刷新缓存后重试

### 想用新的颜色或图标？

当前预置了 4 种颜色（`blue`、`violet`、`amber`、`rose`）和 4 种图标（`Layers`、`Search`、`Flame`、`Scissors`）。使用不在列表中的值会回退到默认值（`blue` + `Layers`），不会报错。如果需要新增颜色或图标，需要开发者在前端配置中添加。

### coming_soon 状态的领域可以有 Tutorial 文件吗？

可以。`coming_soon` 状态下 Tutorial 文件仍会被解析和缓存，但 Portal 不会展示卡片。改为 `active` 后会立即显示。这意味着可以提前准备好所有内容，通过修改 `_index.md` 的 `status` 字段控制上线时间。

### 教程描述（卡片副标题）是怎么确定的？

优先级：
1. 正文 H1 之后的第一段非空非标题文字
2. 若无描述文字，自动生成 `{agent 数量} agents · Level {level}`

### 多个教程之间如何排序？

按文件名的字典序排序。使用数字前缀（`01_`、`02_`、`03_`）可以精确控制顺序。
