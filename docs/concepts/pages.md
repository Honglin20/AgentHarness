# 页面分类（Page Concepts）

TARS Web UI 的所有视图分为 **Portal 阶段**（进入 workflow 之前）和 **Workflow 阶段**（启动后/特殊状态）。共 9 个独立页面。

**状态机入口**：`frontend/src/stores/portalStore.ts` 的 `portalView: "home" | "workflows" | "tutorial" | "api-doc"`，加上 `useWorkflowStore` 的 `status / selectedTemplate` 和 `useViewStore` 的 `activeView`，组合决定渲染哪个页面。

**统一渲染入口**：`frontend/src/components/layout/ScopedCenterPanel.tsx` —— 按优先级 if/else 分支选择页面。

---

## 1. 主页面（Domain Portal）

| 字段 | 内容 |
|------|------|
| **职责** | 全应用入口。按"领域"分组展示教学卡片，可下钻到该领域的 workflows / tutorial / api-doc |
| **组件** | `frontend/src/components/portal/DomainPortal.tsx` |
| **触发** | `portalView === "home"` + `isIdle` + `!selectedTemplate`（首访 `/` 或刷新后默认） |
| **URL** | `/`（无 query） |

---

## 2. 教学页面（Tutorial Page）

| 字段 | 内容 |
|------|------|
| **职责** | 单个 tutorial 的 markdown 阅读 + MiniDag 导航 + Level 切换；右栏 chapter nav，左栏 MiniDag + 章节列表，"Try it" 按钮一键载入对应 workflow |
| **组件** | `frontend/src/components/portal/DomainTutorialPage.tsx` |
| **触发** | `portalView === "tutorial"`（来自 `showTutorial(domainId, tutorialId)`） |
| **URL** | `/?view=tutorial&domain=<id>&tutorial=<id>` |

---

## 3. 生产页面（Workflows Page）

| 字段 | 内容 |
|------|------|
| **职责** | 某个 domain 下所有"生产级"workflow 的卡片列表，点卡片进入启动页面；底部列出其他 domain 的入口 |
| **组件** | `frontend/src/components/portal/DomainWorkflowsPage.tsx` |
| **触发** | `portalView === "workflows"`（主页"Workflows →"按钮 / 启动页"New Workflow"回跳） |
| **URL** | `/?view=workflows&domain=<id>` |

---

## 4. 启动页面（Idle / Template Preview）

| 字段 | 内容 |
|------|------|
| **职责** | template 已选中但尚未启动的"准备态"。显示 DAG 预览 + "Ready to start \<name\>" + ChatInput（输入任务即可启动） |
| **组件** | 无独立组件，`ScopedCenterPanel.tsx` 末段 inline 渲染（`DAGPreview` + ChatInput） |
| **触发** | `isIdle && selectedTemplate`（`setSelectedTemplate` + `previewTemplate`，来自教学页 "Try it" 或生产页卡片点击） |
| **URL** | 无 query（template 在 store 内，不进 URL） |

---

## 5. API 文档页面（API Doc Page）

| 字段 | 内容 |
|------|------|
| **职责** | 单个 API 的 markdown 召考；左栏列出 domain 内其他 API + 引用此 API 的 tutorial 列表 |
| **组件** | `frontend/src/components/portal/ApiDocPage.tsx` |
| **触发** | `portalView === "api-doc"`（tutorial 页右栏的 API 链接 / API 文档页左栏的"其他 API"） |
| **URL** | `/?view=api-doc&domain=<id>&api=<name>` |

---

## 6. 运行页面（Running / Live Workflow）

| 字段 | 内容 |
|------|------|
| **职责** | workflow 启动后的工作面板。Conversation/Results/Analysis 三 tab，DAG 实时高亮当前节点，右栏 Diagnostics 显示 trace/tool/error |
| **组件** | `ScopedCenterPanel.tsx` 末段的 `showTabs` 分支（`ScopedConversationTab` / `ScopedResultsTab` / `ScopedAnalysisTab`） |
| **触发** | `!isIdle && !isReplay`（`status` ∈ `running / completed / failed / paused / cancelled / interrupted`） |
| **URL** | `/?wid=<runId>&wf=<workflowName>`（live） |

---

## 7. 回放页面（Replay View）

| 字段 | 内容 |
|------|------|
| **职责** | 历史 run 的只读视图，复用运行页面的 tab 布局，但禁用所有写操作（ChatInput 隐藏，header 显示 "REPLAY · \<workflow_name\>" 角标） |
| **组件** | 同运行页面，靠 `isReplayProp` 切换只读分支 |
| **触发** | `activeView.type === "replay"`（侧边栏 `RunHistoryList` 点击历史 run） |
| **URL** | `/?run=<runId>` |

---

## 8. Benchmark 页面（Benchmark View）

| 字段 | 内容 |
|------|------|
| **职责** | 基准测试任务编辑 + 批量运行；左侧 task 列表，右侧编辑 + 运行状态。chatInput 区用作 benchmark 启动 |
| **组件** | `frontend/src/components/center-panel/BenchmarkView.tsx` |
| **触发** | `activeBenchmark`（侧边栏 Benchmarks 区点 benchmark 名称） |
| **URL** | `/?bench=<name>`（运行时附 `&task=<runId>` 标识当前选中任务） |

---

## 9. 错误页面（Workflow Error）

| 字段 | 内容 |
|------|------|
| **职责** | workflow 启动失败或运行中严重错误的全屏提示，retry / reload 按钮 |
| **组件** | `ScopedCenterPanel.tsx` 内 inline 渲染 |
| **触发** | `workflowError && !isReplay`（`outputStore.setWorkflowError()` 在 `workflow.error` 事件中被调用） |
| **URL** | 无独立 URL（沿用当前 wid/wf） |

---

## 跳转关系图

```
                        ┌─────────────────────────┐
                        │  1. 主页面 (DomainPortal)│
                        │  default /?             │
                        └──────────┬──────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
       Tutorial │click             │click "Workflows"  │ other-domain
                ▼                  ▼                    ▼
   ┌───────────────────┐  ┌───────────────────┐  (drill in)
   │ 2. 教学页面        │  │ 3. 生产页面        │
   │ ?view=tutorial    │  │ ?view=workflows   │◀─────┐
   └─────┬──────┬──────┘  └─────────┬─────────┘      │
         │      │                   │ card click      │
         │      │ "$.api-doc"       │                 │
         │      ▼                   ▼                 │
         │   ┌───────────────────┐  ┌───────────────────┐
         │   │ 5. API 文档页面   │  │ 4. 启动页面        │
         │   │ ?view=api-doc     │  │ (template ready)  │
         │   │ (来自教学右栏)    │  └─────┬─────────────┘
         │   └───────────────────┘        │ ChatInput submit
         │                                ▼
         │                       ┌───────────────────┐
         │                       │ 6. 运行页面        │
         │       "New Workflow"  │ ?wid&wf           │
         │ ◀─────────────────────┤                   │
         │                       └─────┬─────────────┘
         │                             │ history click
         │                             ▼
         │                       ┌───────────────────┐
         │                       │ 7. 回放页面        │
         │                       │ ?run=<id>         │
         │                       └───────────────────┘
         │
         │ sidebar benchmark       ┌───────────────────┐
         └───────────────────────▶│ 8. Benchmark 页面 │
                                   │ ?bench=<name>     │
                                   └───────────────────┘

   workflow.error 沿用当前 URL ──▶ 9. 错误页面
```

**关键转换**：
- **Try it / 卡片点击**：只写 `setSelectedTemplate + previewTemplate`，`portalView` 保留供 "New Workflow" 回跳时定位 domain
- **New Workflow（启动页/运行页）**：`resetWorkflow()` → 如果当前 `workflowName` 能在 domains 里找到 → `showWorkflows(domain)`；否则 `goHome()`
- **History → 回放**：`fetchRun(runId)` → `showReplay(run)`
- **侧边栏 Benchmark**：`setActiveBatch(name)` + 父组件 `setActiveBenchmark(name)`
