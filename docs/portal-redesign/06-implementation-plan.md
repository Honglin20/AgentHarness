# 实施计划

## 改动面总览

### 后端
- MD 解析脚本（扫描 `tutorials/` → 输出 JSON）
- 新 API：`GET /api/domains`（领域列表 + 教程元数据 + API 文档列表）
- 新 API：`GET /api/domains/{domain}/tutorials/{id}/sections/{agent}`（单章节内容）
- 新 API：`GET /api/domains/{domain}/api/{name}`（API 文档内容）

### 前端
- **改造 CenterPanel 落地页** → 领域门户首页（领域卡片）
- **新增 DomainTutorialPage** — 教学页（左右分栏，DAG+章节合并）
- **新增 DomainWorkflowsPage** — 生产工作流页（领域分区卡片）
- **新增 ApiDocPage** — API 文档详情页
- **视图路由** — CenterPanel 内部状态切换（类似 benchmark 模式）

### 数据/内容
- 创建 `tutorials/quantization/` 目录结构
- 写 `_index.md` + `01_quick_start.md`（量化 Level 1）
- 教学级 workflow 放到 `workflows/tutorials/`

---

## 分阶段计划

### Phase 1: 数据层 + 门户首页

**目标**：能看到领域卡片，点击可跳转

**后端**：
- 创建 `tutorials/` 目录结构 + `tutorials/quantization/_index.md`
- 编写 MD 解析脚本 `scripts/parse_tutorials.py`
  - 输入：`tutorials/` 目录
  - 输出：领域列表 JSON（domain, title, color, icon, status, tutorials[], apis[]）
- 新增 API `GET /api/domains` — 调用解析脚本或缓存结果

**前端**：
- 改造 `CenterPanel.tsx` 的 idle 落地页
  - `fetch /api/domains` 获取领域列表
  - 渲染领域卡片（颜色、icon、状态）
  - [学习] / [工作流] 按钮点击 → 切换到对应视图

**交付物**：
- 门户首页可渲染，能看到量化卡片
- 点击按钮暂时为空页面（placeholder）

---

### Phase 2: 生产工作流页

**目标**：领域分区展示 workflow，点击可启动

**后端**：
- 扩展 `GET /api/domains` 返回的 workflow 列表
  - 区分教学/生产：被教程引用的 = 教学，其余 = 生产
  - 或按目录：`workflows/tutorials/` vs `workflows/<domain>/`
- 复用现有 `GET /api/workflows/definitions` 的数据

**前端**：
- 新组件 `DomainWorkflowsPage`
  - 领域分区 section（左色条 + 标题）
  - 每个领域下展示生产 workflow 卡片
  - 点击卡片 → 复用现有逻辑 `setSelectedTemplate` → DAG 预览 + ChatInput
- 视图切换：CenterPanel 内部 state 管理（`portalView: "home" | "workflows"`）

**交付物**：
- 生产工作流页可用，点卡片能启动 workflow

---

### Phase 3: 教学页

**目标**：左右分栏，章节与 DAG 合并，可阅读教程

**后端**：
- 新增 API `GET /api/domains/{domain}/tutorials/{id}` — 返回完整教程数据
  - sections 列表（title, agent, markdown 内容）
  - 关联 workflow 的 DAG 拓扑（从 workflow.json 读取）
- 新增 API `GET /api/domains/{domain}/tutorials/{id}/sections/{agent}` — 单章节内容

**前端**：
- 新组件 `DomainTutorialPage`
  - 左面板：DAG 章节导航（合并渲染）
    - 节点样式：当前（蓝）/ 已完成（绿）/ 未到达（灰）
    - 点击节点 → 右侧滚动到对应章节
    - API 文档列表（底部）
  - 右面板：Markdown 渲染
    - IntersectionObserver 检测当前阅读章节 → 左侧高亮
  - 顶部 Level tabs 切换
  - 底部 [试一试 ▶] → 选中 workflow → 进入运行界面
- 视图切换扩展：`portalView: "home" | "workflows" | "tutorial"`
  - 新增 `tutorialContext: { domain, tutorialId, level }`

**交付物**：
- 教学页可用，量化 Level 1 教程可阅读 + DAG 联动

---

### Phase 4: API 文档页

**目标**：API 详情可阅读，与教学页双向跳转

**后端**：
- 新增 API `GET /api/domains/{domain}/api/{name}` — 返回 API 文档 markdown
- 解析脚本增加：提取正文中的 `](api/xxx.md)` 链接，建立反向映射

**前端**：
- 新组件 `ApiDocPage`
  - 渲染 API 文档 markdown
  - 底部："相关教程"（反向映射）、"其他 API"（同领域列表）
- 视图切换扩展：`portalView: "home" | "workflows" | "tutorial" | "api-doc"`

**交付物**：
- API 文档页可用，教学页 ↔ API 页可互相跳转

---

### Phase 5: 内容填充 + 打磨

**目标**：量化领域内容完整，体验打磨

**内容**：
- 写 `tutorials/quantization/02_diagnostic.md`（Level 2）
- 写 `tutorials/quantization/03_full_chain.md`（Level 3）
- 写 `tutorials/quantization/api/quantizer.md` + `study_runner.md` + `adapter.md`
- 创建 NAS 领域骨架（`_index.md` + placeholder）

**打磨**：
- coming soon 领域的灰度展示
- 颜色主题一致性
- 响应式布局
- 移动端适配（如果需要）

**交付物**：
- 量化领域完整（3 个 Level + API 文档）
- NAS 骨架 ready

---

## 视图状态管理

当前 CenterPanel 通过条件判断渲染不同视图。新增的页面用类似的模式：

```typescript
// viewStore 扩展
type PortalView = "home" | "workflows" | "tutorial" | "api-doc";

interface PortalState {
  portalView: PortalView;
  portalContext: {
    domain?: string;          // 当前领域
    tutorialId?: string;      // 当前教程
    apiName?: string;         // 当前 API 文档
  };
}
```

当 workflow 启动后（`workflowId` 存在），portal 视图自动让位给运行界面。

---

## 文件清单预估

### 新增文件

```
scripts/parse_tutorials.py                           # MD 解析脚本
tutorials/quantification/_index.md                   # 领域元数据
tutorials/quantification/01_quick_start.md           # Level 1 教程
tutorials/quantification/api/quantizer.md            # API 文档
server/domain_routes.py                              # 新 API 路由
frontend/src/components/portal/DomainPortal.tsx       # 门户首页
frontend/src/components/portal/DomainCard.tsx         # 领域卡片
frontend/src/components/portal/DomainWorkflowsPage.tsx # 生产工作流页
frontend/src/components/portal/DomainTutorialPage.tsx  # 教学页
frontend/src/components/portal/ApiDocPage.tsx         # API 文档页
frontend/src/components/portal/DagChapterNav.tsx      # 左侧 DAG+章节导航
frontend/src/stores/portalStore.ts                   # 视图状态
```

### 修改文件

```
server/app.py              # 注册新路由
server/routes.py           # 或新建 domain_routes
frontend/src/components/layout/CenterPanel.tsx  # 改造落地页
frontend/src/components/layout/HeaderBar.tsx    # 返回按钮
```
