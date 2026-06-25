# Workflows 编写指南

本文档面向**工作流编写者**，介绍如何创建、组织和管理 workflow。

---

## 目录

- [1. 整体架构概览](#1-整体架构概览)
- [2. 目录结构](#2-目录结构)
- [3. workflow.json 结构](#3-workflowjson-结构)
- [4. Agent 编写](#4-agent-编写)
- [5. 工作流的可见性](#5-工作流的可见性)
- [6. 如何让工作流出现在 Portal 页面](#6-如何让工作流出现在-portal-页面)
- [7. 创建新工作流（端到端）](#7-创建新工作流端到端)
- [8. 三种作用域：Legacy / Shared / Private](#8-三种作用域legacy--shared--private)
- [9. 常见问题](#9-常见问题)

---

## 1. 整体架构概览

```
workflows/
├── <workflow-name>/           # Legacy 工作流（全局可见）
│   ├── workflow.json          #   工作流定义（必须）
│   ├── agents/                #   Agent MD 文件（必须）
│   └── scripts/               #   辅助脚本（可选）
├── _shared/                   # 共享工作流（所有用户可见）
│   └── workflows/
│       └── <name>/
│           ├── workflow.json
│           └── agents/
├── users/                     # 用户私有工作流
│   └── <user-id>/
│       └── workflows/
│           └── <name>/
│               ├── workflow.json
│               └── agents/
└── README.md                  # 本文件
```

---

## 2. 目录结构

一个完整的工作流目录包含：

```
workflows/<workflow-name>/
├── workflow.json          # 工作流定义（必须）
├── agents/                # Agent 指令文件（必须）
│   ├── agent_a.md         #   每个 agent 一个 MD 文件
│   ├── agent_b.md
│   └── _judge_agent_x.md  #   Eval 评审 agent（自动生成，以 _ 开头）
└── scripts/               # 辅助脚本（可选）
    └── helper.py
```

**规则**：
- 目录名 = 工作流名（`name` 字段应与目录名一致）
- `workflow.json` 是唯一必须的配置文件
- `agents/` 目录下每个 `.md` 文件对应一个 agent 的系统提示
- `scripts/` 目录用于存放 agent 可能调用的辅助脚本
- 不包含 `workflow.json` 的目录会被系统忽略

---

## 3. workflow.json 结构

### 3.1 基本结构

```json
{
  "name": "my-workflow",
  "agents": [
    {
      "name": "analyzer",
      "after": [],
      "tools": ["bash", "grep", "glob", "read_text_file"],
      "model": null,
      "retries": 3,
      "result_type_name": "ProjectAnalysis",
      "result_type_schema": {
        "properties": {
          "model_class": { "type": "string", "description": "模型类名" },
          "dataset": { "type": "string", "description": "数据集名称" }
        },
        "required": ["model_class", "dataset"]
      }
    },
    {
      "name": "runner",
      "after": ["analyzer"],
      "tools": ["bash"],
      "retries": 2
    },
    {
      "name": "reporter",
      "after": ["runner"],
      "tools": ["render_chart", "read_text_file", "bash"]
    }
  ]
}
```

### 3.2 Agent 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | 字符串 | 是 | Agent 名称，必须与 `agents/` 目录下的 MD 文件名一致（不含 `.md`） |
| `after` | 字符串列表 | 是 | 依赖的前置 agent。空列表 `[]` 表示起始节点 |
| `tools` | 字符串列表 | 否 | Agent 可使用的工具列表。省略则使用默认工具集 |
| `model` | 字符串 \| null | 否 | 指定模型。`null` 使用默认模型 |
| `retries` | 整数 | 否 | 失败重试次数。默认 0（不重试） |
| `result_type_name` | 字符串 | 否 | Agent 输出的结构化类型名称 |
| `result_type_schema` | 对象 | 否 | JSON Schema，定义 Agent 输出的结构 |
| `on_pass` | 字符串 | 否 | 条件边：当前 agent 成功时跳转到指定 agent |
| `on_fail` | 字符串 | 否 | 条件边：当前 agent 失败时跳转到指定 agent |
| `eval` | 布尔值 | 否 | 是否启用 Eval 评审。`true` 时需要配合 `EvalJudge` 使用 |

### 3.3 DAG 拓扑

Agent 之间的依赖关系构成 DAG（有向无环图）：

- **`after`** 定义执行顺序：`"after": ["analyzer"]` 表示在 `analyzer` 完成后才执行
- **`on_pass` / `on_fail`** 定义条件分支：根据上游 agent 的结果决定走哪条路径
- 起始 agent：`"after": []`
- 多个 agent 可以 `after` 同一个 agent（并行分支）

```
analyzer (after: [])
    │
    ├── configurator (after: [analyzer])
    │       │
    │       └── runner (after: [configurator])
    │               │
    │               └── reporter (after: [runner])
    │
    └── validator (after: [analyzer])
```

---

## 4. Agent 编写

### 4.1 Agent MD 文件

`agents/` 目录下的每个 `.md` 文件是 agent 的系统提示（system prompt），文件名 = agent name + `.md`。

```
agents/
├── analyzer.md           # agent name: analyzer
├── configurator.md       # agent name: configurator
└── runner.md             # agent name: runner
```

### 4.2 编写规则

- 文件内容就是 agent 的完整指令，会被注入到 LLM 的 system prompt 中
- 支持完整的 Markdown 语法
- `workflow.json` 中的 `tools` 字段决定了 agent 可用的工具，MD 中应说明如何使用这些工具
- `_judge_` 前缀的 agent MD 文件通常由 `EvalJudge` 自动生成，不要手动创建

### 4.3 输出结构化

如果 `workflow.json` 中定义了 `result_type_schema`，agent 的输出会被约束为该 JSON Schema 定义的结构。在 MD 文件中应说明输出字段的含义。

---

## 5. 工作流的可见性

### 5.1 系统发现机制

系统通过 `GET /api/workflows/definitions` API 发现所有工作流，扫描三个来源：

| 来源 | 路径 | 可见性 |
|------|------|--------|
| **Legacy** | `workflows/<name>/workflow.json` | 所有用户（default 用户或未登录时） |
| **Shared** | `workflows/_shared/workflows/<name>/workflow.json` | 所有用户 |
| **Private** | `workflows/users/<user-id>/workflows/<name>/workflow.json` | 仅该用户 |
| **Registry** | 项目注册 + 内置工作流 | 去重后补充 |

只要目录下有 `workflow.json`，就会被 API 发现。

### 5.2 Portal 页面显示机制

**Portal 的 Workflows 页面显示的工作流，与 `workflows/` 目录下的文件不是一一对应的。**

页面上显示的列表来自**领域（Domain）的 `_index.md` 中手动声明**的 `workflows` 字段：

```yaml
# tutorials/quantization/_index.md
---
workflows:
  - name: mxint-analysis
    description: 基础量化分析
  - name: mxint-diagnostic
    description: MXINT 量化诊断
---
```

**规则**：
- 只有在 `_index.md` 的 `workflows` 中列出的工作流才会出现在对应领域的 Workflows 页面
- `name` 必须与 `workflows/` 目录下的工作流目录名一致
- 领域 Workflows 页面会同时显示当前领域的和其他领域的工作流

### 5.3 自动聚合：`project` 合成领域

没有被任何领域 `_index.md` 声明的工作流，会**自动聚合**到一个名为 `project` 的合成领域中出现在 Portal，无需手动声明。

**「认领」判定**（满足任一即视为已被认领，不进 `project`）：
- 出现在某领域 `_index.md` 的 `workflows:` 字段
- 被某教程 frontmatter 的 `workflow:` 字段引用（Try it 按钮）

**聚合范围**：仅当前项目 `workflows/` 根目录下的工作流（即 Registry 的 project 层）。内置工作流（`harness/builtin/workflows/`）、`_shared/`、`users/` 不参与聚合 —— 它们由各自的作用域机制管理。

**特性**：
- 无未认领工作流时，`project` 领域不会出现（不会渲染空卡片）
- `project` 领域排在所有手动声明的领域之后（`order: 99`）
- 添加/删除工作流后，调用 `POST /api/domains/refresh` 刷新缓存即可生效
- `project` 领域是只读的自动聚合，没有教程和 API 文档

### 5.4 当前显示的工作流

| 领域 | 工作流 | 声明位置 |
|------|--------|---------|
| 模型量化 | `mxint-analysis` | `tutorials/quantization/_index.md` |
| 模型量化 | `mxint-diagnostic` | `tutorials/quantization/_index.md` |
| 模型量化 | `precision-diagnostic` | `tutorials/quantization/_index.md` |
| 结构搜索 (NAS) | `nas-search-space` | `tutorials/nas/_index.md` |
| 结构搜索 (NAS) | `nas-proxy-search` | `tutorials/nas/_index.md` |
| 结构搜索 (NAS) | `nas-multi-objective` | `tutorials/nas/_index.md` |

其余在 `workflows/` 目录下的工作流（如 `demo`、`code_review`、`conditional_route` 等）**不会出现在 Portal 页面**，因为它们没有被任何领域的 `_index.md` 声明。

---

## 6. 如何让工作流出现在 Portal 页面

有两种方式，按需选择：

- **自动聚合（推荐，零配置）**：只要把 `workflows/<name>/workflow.json` 放到 `workflows/` 根目录，它就会自动出现在 Portal 的 `project` 合成领域（详见 §5.3），无需任何额外声明。
- **手动声明（指定到具体领域）**：如果你希望工作流出现在某个已有领域（如「模型量化」「NAS」）下而非 `project`，在目标领域的 `_index.md` 中声明它。

### 步骤（手动声明）

1. **确保工作流存在**：`workflows/<name>/workflow.json` 文件已创建

2. **在目标领域的 `_index.md` 中声明**：

```yaml
# tutorials/quantization/_index.md
---
workflows:
  - name: your-workflow-name    # 必须与 workflows/ 目录名一致
    description: 工作流描述文字    # 显示在工作流卡片上
---
```

3. **刷新缓存**：

```bash
curl -X POST http://localhost:8000/api/domains/refresh
```

4. **验证**：进入 Portal → 点击领域的 "Workflows →" 链接，确认新工作流出现

> 自动聚合的 `project` 领域同样受这个缓存控制：磁盘上增删工作流后需调用 `/api/domains/refresh` 才会更新。

### 注意事项

- 一个工作流可以被多个领域声明（跨领域复用）
- 如果工作流只用于 Try it（教学页），不需要在 `_index.md` 中声明。只需要在教程 MD 的 frontmatter 中设置 `workflow: name` 即可（这种引用也算「认领」，工作流不会重复进 `project`）
- 声明在 `_index.md` 中的工作流会同时出现在领域 Workflows 页面和 Try it 按钮中

---

## 7. 创建新工作流（端到端）

### 7.1 创建目录结构

```bash
mkdir -p workflows/my-workflow/agents
mkdir -p workflows/my-workflow/scripts
```

### 7.2 编写 workflow.json

```json
{
  "name": "my-workflow",
  "agents": [
    {
      "name": "collector",
      "after": [],
      "tools": ["bash", "grep", "glob"],
      "retries": 2
    },
    {
      "name": "processor",
      "after": ["collector"],
      "tools": ["bash", "read_text_file", "write_file"],
      "retries": 1
    },
    {
      "name": "reporter",
      "after": ["processor"],
      "tools": ["render_chart", "bash"]
    }
  ]
}
```

### 7.3 编写 Agent 指令

为每个 agent 创建 MD 文件：

```bash
# workflows/my-workflow/agents/collector.md
```

```markdown
You are a data collector agent. Your job is to scan the project directory and gather relevant information.

Steps:
1. Use `glob` to find relevant files
2. Use `grep` to search for key patterns
3. Summarize findings in a structured format

Output the following fields:
- `files_found`: list of relevant file paths
- `summary`: brief summary of findings
```

### 7.4 可选：在 Portal 中展示

```yaml
# tutorials/some-domain/_index.md
---
workflows:
  - name: my-workflow
    description: 简短描述
---
```

### 7.5 验证

```bash
# 检查工作流是否被系统发现
curl -s http://localhost:8000/api/workflows/definitions | python3 -m json.tool | grep '"name"'

# 检查工作流详情
curl -s http://localhost:8000/api/workflows/definitions | python3 -c "
import sys, json
defs = json.load(sys.stdin)
for d in defs:
    if d['name'] == 'my-workflow':
        print(json.dumps(d, indent=2, ensure_ascii=False))
        break
"
```

---

## 8. 三种作用域：Legacy / Shared / Private

### 8.1 Legacy（默认）

**位置**：`workflows/<name>/workflow.json`

- 所有用户可见（default 用户或未登录时）
- 适用于：框架内置的示例、教程配套的工作流
- 当前大部分工作流都属于 Legacy

### 8.2 Shared

**位置**：`workflows/_shared/workflows/<name>/workflow.json`

- 所有用户可见
- 适用于：团队共享的生产级工作流
- 只有管理员可以删除

### 8.3 Private

**位置**：`workflows/users/<user-id>/workflows/<name>/workflow.json`

- 仅创建者可见
- 适用于：用户自建的实验性工作流
- 用户只能删除自己创建的

### 8.4 查找优先级

当按名称加载工作流时，系统查找顺序：

1. **Registry**（项目注册 + 内置注册）
2. **Legacy 回退**（`workflows/<name>/workflow.json`）

同名工作流，Registry 中的优先。

---

## 9. 常见问题

### 为什么 workflows/ 下有很多工作流但页面上只显示几个？

未被任何领域声明的工作流会自动聚合到 Portal 的 `project` 合成领域（详见 §5.3）。而各专属领域（模型量化、NAS 等）下只显示在该领域 `tutorials/<domain>/_index.md` 的 `workflows` 字段中手动声明的工作流。若希望某个工作流出现在某个具体领域而非 `project`，需要在对应 `_index.md` 中声明。

### 工作流可以被多个领域复用吗？

可以。同一个工作流可以在多个领域的 `_index.md` 中声明，也可以被多个教程的 `workflow` 字段引用。

### 创建了工作流但 Try it 按钮点了没反应？

1. 确认 `workflows/<name>/workflow.json` 文件存在
2. 确认 `GET /api/workflows/definitions` API 能返回该工作流
3. 确认教程 MD 中 `workflow` 字段的值（取 `/` 最后一段）与工作流 `name` 一致

### 工作流目录下没有 `agents/` 目录会怎样？

Agent 指令文件是运行时必需的。如果缺少对应的 `.md` 文件，agent 启动时会没有系统提示，行为不可预期。创建工作流时务必确保每个 agent 都有对应的 MD 文件。

### `_shared/` 目录下的共享工作流和 Legacy 工作流有什么区别？

- **Legacy**：直接放在 `workflows/` 根目录，全局可见，所有用户都能看到
- **Shared**：放在 `workflows/_shared/workflows/` 下，同样是全局可见，但只有管理员可删除
- **Private**：放在 `workflows/users/<id>/workflows/` 下，仅创建者可见

功能上 Legacy 和 Shared 的主要区别在于权限管理。

### 如何调试工作流？

```bash
# 列出所有被系统发现的工作流
curl -s http://localhost:8000/api/workflows/definitions | python3 -m json.tool

# 查看特定工作流的 DAG 结构
curl -s http://localhost:8000/api/workflows/definitions | python3 -c "
import sys, json
for d in json.load(sys.stdin):
    if d['name'] == 'TARGET_NAME':
        print(json.dumps(d['dag'], indent=2))
"

# 验证工作流能否被加载（Python）
python -c "from harness.core.workflow_persist import load_workflow; wf = load_workflow('my-workflow'); print(wf.name, [a.name for a in wf.agents])"
```
