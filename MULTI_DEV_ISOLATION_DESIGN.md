# Multi-Developer Isolation Design Document

## 概述

本文档记录多开发者隔离系统的设计方案、实现细节和开发进度。

---

## 一、需求背景

### 1.1 三个使用场景

| 场景 | 用户类型 | 核心需求 |
|------|---------|---------|
| **开发者创作** | 开发者 | 私有 workflows 互不可见，共享 workflows 可见 |
| **开发者测试** | 开发者 | 指定工作目录，在该目录下运行 workflow |
| **终端用户** | 非技术用户 | 上传代码，选择 workflow，运行 |

### 1.2 核心问题

1. **Workflow 可见性**：不同开发者不应看到彼此的私有 workflows
2. **运行记录隔离**：不同开发者不应看到彼此的运行记录
3. **工作目录支持**：允许用户指定代码所在目录作为工作空间

---

## 二、设计方案

### 2.1 目录结构

```
workflows/
├── _shared/                      # 共享（所有人只读）
│   ├── agents/
│   └── workflows/
│       ├── code_review/
│       ├── chart_demo/
│       └── ...
└── users/                        # 私有
    └── {user_id}/
        └── workflows/
            ├── my_workflow_1/
            └── my_workflow_2/

users.json                        # API Key → user_id 映射
{
  "dev_alice": {"user_id": "alice", "name": "Alice", "role": "developer"},
  "dev_bob": {"user_id": "bob", "name": "Bob", "role": "developer"},
  "admin": {"user_id": "admin", "name": "Admin", "role": "admin"}
}
```

### 2.2 核心概念

| 概念 | 说明 |
|------|------|
| **user_id** | 用户唯一标识，来自 API Key |
| **scope** | workflow 范围：`shared`（共享）或 `private`（私有）|
| **work_dir** | 工作目录，workflow 执行时切换到该目录 |
| **role** | 用户角色：`developer`（开发者）或 `admin`（管理员）|

---

## 三、API 设计

### 3.1 认证方式

通过 Header 传递 API Key：
```
X-API-Key: dev_alice
```

### 3.2 端点改动

| 端点 | 改动 | 权限 |
|------|------|------|
| `GET /api/workflows/definitions` | 返回共享 + 当前用户私有 | 所有用户 |
| `DELETE /api/workflows/definitions/{name}` | 只能删除私有 workflow，admin 可删除共享 | owner 或 admin |
| `POST /api/workflows` | 增加 `work_dir` 参数 | 所有用户 |
| `GET /api/runs` | 只返回当前用户的 runs | 所有用户 |
| `DELETE /api/runs/{run_id}` | 只能删除自己的 run | owner |

### 3.3 请求/响应格式

#### 获取 Workflows
```json
GET /api/workflows/definitions
Headers: X-API-Key: dev_alice

Response:
[
  {
    "name": "code_review",
    "scope": "shared",
    "agents": [...],
    "dag": {...}
  },
  {
    "name": "my_workflow",
    "scope": "private",
    "agents": [...],
    "dag": {...}
  }
]
```

#### 运行 Workflow
```json
POST /api/workflows
Headers: X-API-Key: dev_alice
Body:
{
  "name": "my_run",
  "workflow": "code_review",
  "inputs": {"task": "Review main.py"},
  "work_dir": "/path/to/user/code"
}
```

---

## 四、前端设计

### 4.1 UI 改动

| 组件 | 改动 |
|------|------|
| **TemplateLibrary** | 显示 scope 标签，hover 右上角显示删除按钮 |
| **WorkflowLauncher** | 增加 work_dir 输入框 |
| **HeaderBar** | 显示当前用户信息 + 设置入口 |
| **ApiKeySettings**（新增） | 设置 API Key |

### 4.2 UI 示例

#### TemplateLibrary
```
┌─────────────────────────────────────────┐
│ Code Review    [Shared]        [🗑️]     │
│ My Workflow    [Private]       [🗑️]     │
└─────────────────────────────────────────┘
```

#### WorkflowLauncher
```
┌─────────────────────────────────────────┐
│ Workflow: [Code Review       ▼]         │
│ Work Dir:  [/Users/alice/code]          │
│ Task:     [Review main.py     ]         │
│ [ Run Workflow ]                        │
└─────────────────────────────────────────┘
```

---

## 五、实现进度

### Phase 1: 后端核心
- [x] 设计文档保存
- [ ] 创建 `harness/user_manager.py`
- [ ] 修改 `Workflow.list_saved()` 增加用户隔离
- [ ] API 端点增加用户过滤和权限检查
- [ ] 增加 work_dir 参数支持
- [ ] 运行记录增加 user_id 并过滤

### Phase 2: 前端改动
- [ ] 创建 `frontend/src/lib/api.ts`
- [ ] 创建 `ApiKeySettings.tsx`
- [ ] 修改 `TemplateLibrary.tsx`
- [ ] 修改 `WorkflowLauncher.tsx`
- [ ] 修改 `HeaderBar.tsx`

### Phase 3: 配置和迁移
- [ ] 创建迁移脚本 `migrate_to_user_isolated.py`
- [ ] 创建 `users.json`
- [ ] 更新 `.gitignore`

---

## 六、代码改动范围

| 文件 | 改动 | 预估行数 |
|------|------|---------|
| `harness/user_manager.py` | 新增 | ~50 行 |
| `harness/api.py` | 修改 | ~30 行 |
| `server/routes.py` | 修改 | ~50 行 |
| `server/runner.py` | 修改 | ~10 行 |
| `harness/run_store.py` | 修改 | ~10 行 |
| `frontend/src/lib/api.ts` | 新增 | ~30 行 |
| `frontend/src/components/settings/ApiKeySettings.tsx` | 新增 | ~80 行 |
| `frontend/src/components/sidebar/TemplateLibrary.tsx` | 修改 | ~30 行 |
| `frontend/src/components/output/WorkflowLauncher.tsx` | 修改 | ~20 行 |
| `frontend/src/components/layout/HeaderBar.tsx` | 修改 | ~20 行 |
| **总计** | | ~330 行 |

---

## 七、边界情况处理

| 情况 | 处理方式 |
|------|---------|
| 未设置 API Key | 使用默认用户，显示提示 |
| API Key 无效 | 返回 401，提示重新输入 |
| 工作目录不存在 | 返回错误，提示检查路径 |
| 删除共享 workflow（非 admin）| 返回 403 |
| 删除他人 run | 返回 403 |

---

## 八、后续扩展路径

```
Phase 1: Workflow 隔离 + Run 隔离 + work_dir
   ↓
Phase 2: WebSocket 隔离
   ↓
Phase 3: 终端用户智能引导
   ↓
Phase 4: 配额/审计/更细粒度权限
```

---

## 九、版本历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v1.0 | 初始设计文档 |
| 2026-05-26 | v2.0 | 实现完成 - 多开发者隔离功能 |

---

## 十、实现状态（v2.0）

### 已完成 ✅

#### Phase 1: 后端核心
- ✅ `harness/user_manager.py` - 用户认证、API Key 映射、权限检查
- ✅ `Workflow.list_saved(user_id)` - 用户隔离的 workflow 列表
- ✅ API 端点用户过滤 (`/api/workflows/definitions`, `/api/runs`)
- ✅ 权限检查（删除操作）
- ✅ `work_dir` 参数支持
- ✅ `user_id` 在运行记录中的持久化

#### Phase 2: 前端改动
- ✅ `frontend/src/lib/api.ts` - fetchWithAuth 封装
- ✅ `frontend/src/components/settings/ApiKeySettings.tsx` - API Key 设置
- ✅ `frontend/src/components/ui/label.tsx` - Label 组件
- ✅ `frontend/src/components/sidebar/TemplateLibrary.tsx` - scope 标签显示
- ✅ `frontend/src/components/output/WorkflowLauncher.tsx` - work_dir 输入
- ✅ `frontend/src/components/layout/HeaderBar.tsx` - 用户显示和设置入口

#### Phase 3: 配置和迁移
- ✅ `scripts/migrate_to_user_isolated.py` - 迁移脚本
- ✅ `users.json` - 用户配置示例
- ✅ `.gitignore` - 排除 users.json

### 使用方式

#### 1. 配置用户

编辑 `users.json`：
```json
{
  "dev_alice": {"user_id": "alice", "name": "Alice", "role": "developer"},
  "dev_bob": {"user_id": "bob", "name": "Bob", "role": "developer"},
  "admin": {"user_id": "admin", "name": "Admin", "role": "admin"}
}
```

#### 2. 运行迁移脚本

```bash
python scripts/migrate_to_user_isolated.py
```

这将把现有 workflows 移到 `workflows/_shared/workflows/`。

#### 3. 前端设置 API Key

1. 点击右上角用户名
2. 输入 API Key（如 `dev_alice`）
3. 点击保存

#### 4. 运行 workflow 并指定工作目录

在 WorkflowLauncher 中：
- 选择 workflow
- 输入工作目录路径（可选）
- 点击 Run

### API Key 示例

| API Key | 用户 | 角色 | 说明 |
|---------|------|------|------|
| `dev_alice` | Alice | developer | 开发者 Alice |
| `dev_bob` | Bob | developer | 开发者 Bob |
| `admin` | Admin | admin | 管理员 |
| `user_default` | Default | developer | 默认用户 |

### 权限矩阵

| 操作 | 共享 Workflow | 私有 Workflow | 删除 Run |
|------|---------------|---------------|---------|
| 查看 | ✅ 所有用户 | ✅ 所属用户 | ✅ 所有用户（只看自己的）|
| 运行 | ✅ 所有用户 | ✅ 所属用户 | - |
| 编辑 | ❌ | ✅ 所属用户 | - |
| 删除 | ✅ admin | ✅ 所属用户 | ✅ owner 或 admin |