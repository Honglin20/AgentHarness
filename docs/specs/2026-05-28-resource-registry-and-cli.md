# SPEC: Resource Registry + CLI Command

**日期**: 2026-05-28
**状态**: IMPLEMENTED (Phase 1-3 完成，Phase 4 待定)
**优先级**: P1

---

## 1. 问题陈述

AgentHarness 安装为 pip 包后存在三个核心缺陷：

1. **无内置资源**: `workflows/` 和 `benchmarks/` 不在 package 内，pip install 后是空的
2. **无注册机制**: 开发者无法从任意路径注册自定义 workflow/benchmark
3. **无 CLI 命令**: 启动 UI 依赖 `bash examples/launch_ui.sh`，用户在自己的项目目录下无法启动

## 2. 设计目标

- `pip install agent-harness` 后自带示例 workflow + benchmark，开箱可演示
- 开发者用纯 Python API 注册自定义资源，零配置文件
- `harness ui` 一条命令启动 Web UI，可在任意目录执行
- 前端区分 Builtin / Project 资源，Builtin 只读

## 3. 三层资源模型

```
优先级: Project(高) → Builtin(低)
同名覆盖: Project 优先
```

| 层 | 位置 | 说明 | 可写 |
|---|---|---|---|
| **Builtin** | `harness/builtin/workflows/`、`harness/builtin/benchmarks/`（package data） | 随 pip 发布的示例 | 否 |
| **Project** | CWD 下 `workflows/`、`benchmarks/` | 开发者在项目目录下创建 | 是 |

> **决策**: 去掉 User 层（`~/.agent-harness/`）。用户隔离已有 user_manager 处理，资源注册不需要第三层。如未来有跨项目共享需求再加。

## 4. ResourceRegistry

### 4.1 核心接口

```python
# harness/registry.py (新文件)

from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class ResourceMeta:
    name: str
    scope: str            # "builtin" | "project"
    resource_dir: Path    # 绝对路径
    description: str = ""

class ResourceRegistry:
    """三层资源解析器。进程级单例。"""

    def __init__(self, project_root: Path | None = None):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._extra_workflows: list[Path] = []
        self._extra_benchmarks: list[Path] = []

    # --- 注册 ---

    def register_workflow(self, path: str | Path) -> None:
        """注册一个 workflow 目录（须含 workflow.json）。"""
        ...

    def register_benchmark(self, path: str | Path) -> None:
        """注册一个 benchmark 目录（须含 benchmark.json）。"""
        ...

    # --- 发现 ---

    def list_workflows(self, scope: str | None = None) -> list[ResourceMeta]:
        """
        按优先级返回: Extra → Project → Builtin
        scope 过滤: None=全部, "builtin", "project"
        同名去重: Extra > Project > Builtin
        """
        ...

    def list_benchmarks(self, scope: str | None = None) -> list[ResourceMeta]:
        """同上逻辑"""
        ...

    def resolve_workflow(self, name: str) -> ResourceMeta:
        """按名称解析，优先 Project。找不到则 raise FileNotFoundError。"""
        ...

    def resolve_benchmark(self, name: str) -> ResourceMeta:
        """同上"""
        ...

    # --- 路径 ---

    @property
    def builtin_dir(self) -> Path:
        """harness/builtin/ — 通过 __file__ 定位"""
        return Path(__file__).resolve().parent / "builtin"

    @property
    def project_workflows_dir(self) -> Path:
        return self.project_root / "workflows"

    @property
    def project_benchmarks_dir(self) -> Path:
        return self.project_root / "benchmarks"
```

### 4.2 发现逻辑

```
list_workflows():
  1. 扫描 _extra_workflows (程序化注册)
  2. 扫描 project_root/workflows/*/workflow.json
  3. 扫描 harness/builtin/workflows/*/workflow.json
  同名去重: Extra > Project > Builtin
```

### 4.3 全局单例

```python
# harness/registry.py 底部

_global_registry: ResourceRegistry | None = None

def get_registry() -> ResourceRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ResourceRegistry()
    return _global_registry

def configure(project_root: str | Path | None = None) -> ResourceRegistry:
    """重置全局 registry（用于测试或自定义 root）。"""
    global _global_registry
    _global_registry = ResourceRegistry(project_root)
    return _global_registry
```

### 4.4 对外暴露

```python
# harness/__init__.py 更新
from harness.registry import get_registry, configure

__all__ = ["Agent", "Workflow", "Benchmark", "configure", "get_registry"]
```

## 5. 内置资源（Package Data）

### 5.1 目录结构

```
harness/
├── builtin/
│   ├── workflows/
│   │   └── demo_pipeline/
│   │       ├── workflow.json
│   │       └── agents/
│   │           └── analyzer.md
│   └── benchmarks/
│       └── smoke-test/
│           └── benchmark.json
```

### 5.2 pyproject.toml

```toml
[tool.setuptools.package-data]
harness = ["builtin/**/*"]
```

### 5.3 将现有 workflows/demo_pipeline 迁移到 builtin

当前 `workflows/demo_pipeline/` 下的内容复制到 `harness/builtin/workflows/demo_pipeline/`。
保留项目根目录 `workflows/` 给开发者使用（gitignore 不追踪，或追踪为示例）。

## 6. CLI 命令

### 6.1 入口

```toml
# pyproject.toml
[project.scripts]
harness = "harness.cli:main"
```

### 6.2 命令设计

```bash
harness ui [--port PORT] [--host HOST] [--project-root DIR] [--open]

harness list                       # 列出所有已注册的 workflow + benchmark
harness list --scope builtin       # 只看内置
harness list --scope project       # 只看项目级

harness run <workflow> --input '{"task": "..."}'   # CLI 运行 workflow
```

### 6.3 `harness/cli.py` 实现

```python
# harness/cli.py (新文件)

import argparse
import sys

def cmd_ui(args):
    """启动 Web UI"""
    import os
    from harness.registry import configure, get_registry

    if args.project_root:
        configure(args.project_root)

    # 设置环境变量让 server 能找到 project root
    if args.project_root:
        os.environ["HARNESS_PROJECT_ROOT"] = str(args.project_root)

    port = args.port or int(os.environ.get("HARNESS_PORT", "8000"))
    host = args.host or os.environ.get("HARNESS_HOST", "0.0.0.0")

    import uvicorn
    print(f"AgentHarness UI: http://{host}:{port}")
    if args.open:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    uvicorn.run("server.app:app", host=host, port=port, log_level="info")

def cmd_list(args):
    """列出已注册资源"""
    from harness.registry import configure, get_registry
    if args.project_root:
        configure(args.project_root)

    registry = get_registry()
    scope = args.scope

    print("Workflows:")
    for wf in registry.list_workflows(scope=scope):
        print(f"  [{wf.scope}] {wf.name}  ({wf.resource_dir})")

    print("Benchmarks:")
    for bm in registry.list_benchmarks(scope=scope):
        print(f"  [{bm.scope}] {bm.name}  ({bm.resource_dir})")

def main():
    parser = argparse.ArgumentParser(prog="harness", description="AgentHarness CLI")
    sub = parser.add_subparsers(dest="command")

    # harness ui
    ui = sub.add_parser("ui", help="Launch Web UI")
    ui.add_argument("--port", type=int, default=None)
    ui.add_argument("--host", type=str, default=None)
    ui.add_argument("--project-root", type=str, default=None)
    ui.add_argument("--open", action="store_true", help="Open browser")

    # harness list
    ls = sub.add_parser("list", help="List registered resources")
    ls.add_argument("--scope", choices=["builtin", "project"], default=None)
    ls.add_argument("--project-root", type=str, default=None)

    args = parser.parse_args()
    if args.command == "ui":
        cmd_ui(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
```

## 7. 迁移: 现有代码适配

### 7.1 `harness/api.py` — Workflow.load / list_saved / Benchmark.load

**变更**: 从硬编码 `_WORKFLOWS_DIR` / `_BENCHMARKS_DIR` 改为使用 `ResourceRegistry`。

```python
# Before
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"

# After
from harness.registry import get_registry

# Workflow.load(name) → registry.resolve_workflow(name)
# Workflow.list_saved() → registry.list_workflows()
# Benchmark.load(name) → registry.resolve_benchmark(name)
```

**关键**: `Workflow.__init__` 的 `workflow_dir` 参数不变——它仍然由调用方传入。变的是"默认发现"逻辑。

### 7.2 `harness/benchmark_store.py`

`BenchmarkStore.__init__` 需要支持多路径搜索（不再只看单一 `_BENCHMARKS_DIR`）。

**方案**: `BenchmarkStore` 接受 `dirs: list[Path]` 参数，依次搜索。

```python
class BenchmarkStore:
    def __init__(self, dirs: list[Path | str] | None = None):
        if dirs:
            self._dirs = [Path(d) for d in dirs]
        else:
            from harness.registry import get_registry
            reg = get_registry()
            self._dirs = [reg.project_benchmarks_dir, reg.builtin_dir / "benchmarks"]
```

### 7.3 `server/app.py` — 静态文件服务

当前从 `frontend/out/` 提供静态文件。pip install 后需从 package 内提供预构建产物。

**方案**:

```python
# 优先搜索顺序:
# 1. HARNESS_FRONTEND_DIR 环境变量（开发覆盖）
# 2. package 内 frontend/ (开发模式，editable install)
# 3. harness/builtin/frontend/ (pip install 后的预构建产物)

def _resolve_frontend_dir() -> Path:
    env_dir = os.environ.get("HARNESS_FRONTEND_DIR")
    if env_dir:
        return Path(env_dir)

    # Editable install: frontend/ 在 repo root
    dev_path = Path(__file__).resolve().parent.parent / "frontend" / "out"
    if dev_path.exists():
        return dev_path

    # Pip install: pre-built in package
    pkg_path = Path(__file__).resolve().parent / "builtin" / "frontend"
    if pkg_path.exists():
        return pkg_path

    return dev_path  # 不存在则显示 "not built" 页面
```

### 7.4 `server/routes.py` — 资源发现路由

**变更**: `_validate_workflow_dir` 改为使用 registry 解析。

```python
# Before: 硬编码三层路径搜索
# After:
def _validate_workflow_dir(workflow: str, user_id: str | None = None) -> Path:
    from harness.registry import get_registry
    try:
        meta = get_registry().resolve_workflow(workflow)
        return meta.resource_dir
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow}' not found")
```

API 响应增加 `scope` 字段:

```python
@router.get("/workflows/definitions")
async def list_workflow_definitions(request: Request) -> list[dict]:
    from harness.registry import get_registry
    registry = get_registry()
    ...
    # 返回中增加:
    # "scope": meta.scope  # "builtin" | "project"
```

## 8. 前端适配

### 8.1 Scope 展示

**Workflow 列表** (`TemplateLibrary.tsx`):
- Builtin 资源显示 "Built-in" badge（灰色，不可编辑/删除）
- Project 资源显示 "Project" badge（可编辑/删除）
- 去掉旧的 "shared" / "private" / "legacy" 标签

**Benchmark 列表**:
- 同上逻辑

### 8.2 编辑权限

```typescript
// 前端判断
const isReadonly = workflow.scope === "builtin";
// builtin: 隐藏 Delete 按钮，Agent 编辑器 save 按钮禁用
// project: 正常 CRUD
```

## 9. 不做的事情

| 不做 | 原因 |
|------|------|
| User 层（`~/.agent-harness/`） | 用户隔离已有 user_manager，资源不需要第三层 |
| 配置文件（`harness.yaml`） | 纯代码注册，不引入配置文件 |
| `harness run` 命令（本期） | CLI 运行 workflow 优先级低，本期只做 `ui` 和 `list` |
| 前端注册 UI | 开发者通过 Python API 注册，不需要在 UI 上操作 |
| pyproject.toml entry point 注册 | 不用 setuptools entry_points 注册 workflow，保持简单 |

## 10. 实施步骤

### Phase 1: 核心 Registry + 内置资源
1. 创建 `harness/registry.py` — ResourceRegistry + 全局单例
2. 创建 `harness/builtin/` 目录 — 迁移 demo_pipeline + smoke-test
3. 更新 `pyproject.toml` — package-data + console_scripts
4. 单元测试: registry 发现、去重、scope 过滤

### Phase 2: CLI 命令
5. 创建 `harness/cli.py` — `harness ui` + `harness list`
6. 更新 `pyproject.toml` `[project.scripts]`

### Phase 3: 后端适配
7. 重构 `harness/api.py` — Workflow.load / list_saved 改用 registry
8. 重构 `harness/benchmark_store.py` — 支持多路径搜索
9. 重构 `server/routes.py` — _validate_workflow_dir 改用 registry
10. 更新 `server/app.py` — 前端静态文件多路径解析

### Phase 4: 前端适配
11. 更新 `TemplateLibrary.tsx` — scope badge + 只读控制
12. 更新 Benchmark 相关组件 — scope badge
13. 前端 build 并提交产物

## 11. 验收标准

- [ ] `pip install -e .` 后 `harness ui` 可在任意目录启动
- [ ] `harness list` 显示 builtin 资源
- [ ] `Workflow.list_saved()` 返回带 scope 字段的结果
- [ ] `Workflow.load("demo_pipeline")` 能找到 builtin 资源
- [ ] 前端显示 "Built-in" / "Project" badge
- [ ] Builtin 资源不可删除/编辑
- [ ] 开发者在 CWD 下创建 `workflows/my_wf/` 后自动被 `harness list` 发现
- [ ] `registry.register_workflow("/some/path")` 后资源可用
- [ ] 所有现有测试通过（无回归）

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 前端预构建产物体积大（pip 包膨胀） | 可选: 发布为 `agent-harness[ui]` optional dependency，不含预构建产物 |
| editable install vs pip install 路径差异 | `_resolve_frontend_dir()` 覆盖两种场景 + 环境变量 escape hatch |
| 现有代码硬编码 `_WORKFLOWS_DIR` 多处 | Phase 3 逐步迁移，保持旧路径作为 fallback |

---

## 13. 实施记录

### 与原 SPEC 的偏差

1. **Phase 3 采用最小侵入式适配**（非原计划的全量替换）：
   - 不删除 `_WORKFLOWS_DIR` / `_BENCHMARKS_DIR` 常量
   - 不重构 `BenchmarkStore.__init__` 为多路径
   - 不重构 `server/routes.py` 完全改用 registry
   - 而是在 5 个关键入口点加 registry fallback（先查 registry，找不到走旧逻辑）

2. **`list_saved()` 只合并 builtin scope**：
   - 原计划合并所有 registry 资源
   - 实际只合并 `scope="builtin"` 的资源，避免与旧代码的 shared/private/legacy 冲突

3. **新增 `harness/builtin/frontend/`**：
   - 原计划未明确前端打包位置
   - 实际将预构建前端放在 `harness/builtin/frontend/`，随 pip 发布

4. **函数命名**：`configure` → `configure_registry`（避免与 `harness.config.configure` 冲突）

### 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `harness/registry.py` | 新建 | ResourceRegistry + 全局单例 |
| `harness/cli.py` | 新建 | `harness ui` / `harness list` CLI |
| `harness/__init__.py` | 修改 | 导出 `get_registry` / `configure_registry` |
| `harness/builtin/workflows/demo_pipeline/` | 新建 | 内置 workflow（从 `_shared` 复制） |
| `harness/builtin/benchmarks/smoke-test/` | 新建 | 内置 benchmark |
| `harness/builtin/frontend/` | 新建 | 预构建前端（4.2MB） |
| `harness/api.py` | 修改 | `Workflow.load()` / `list_saved()` / `Benchmark._execute()` 加 registry fallback |
| `harness/benchmark_store.py` | 修改 | `load_benchmark()` 加 registry fallback |
| `server/app.py` | 修改 | `_resolve_frontend_dir()` 三路径 fallback |
| `server/routes.py` | 修改 | `_validate_workflow_dir()` 加 registry fallback |
| `pyproject.toml` | 修改 | `[project.scripts]` + `[tool.setuptools.package-data]` |
| `tests/harness/test_registry.py` | 新建 | 22 个单元测试 |
| `tests/test_api_list_saved.py` | 修改 | 隔离 registry 全局状态 |
| `tests/test_routes_new_layout.py` | 修改 | 隔离 registry + 断言过滤 builtin |

### 回退指南

如果 registry 导致问题，可按以下步骤回退：

1. **回退 `harness/api.py`**: 删除所有 `from harness.registry import` 块，恢复旧逻辑
2. **回退 `server/routes.py`**: 删除 `_validate_workflow_dir` 中的 registry fallback 块
3. **回退 `server/app.py`**: 将 `_resolve_frontend_dir()` 替换回 `Path(__file__).parent.parent / "frontend" / "out"`
4. **回退 `harness/benchmark_store.py`**: 删除 `load_benchmark` 中的 registry fallback
5. Registry 模块和 builtin 目录可保留不影响

### 验收状态

- [x] `pip install -e .` 后 `harness ui` 可在任意目录启动
- [x] `harness list` 显示 builtin 资源
- [x] `Workflow.list_saved()` 返回带 scope 字段的结果
- [x] `Workflow.load("demo_pipeline")` 能找到 builtin 资源
- [ ] 前端显示 "Built-in" / "Project" badge（Phase 4）
- [ ] Builtin 资源不可删除/编辑（Phase 4）
- [x] 开发者在 CWD 下创建 `workflows/my_wf/` 后自动被 `harness list` 发现
- [x] `registry.register_workflow("/some/path")` 后资源可用
- [x] 所有现有测试通过（248/248，1 个预先存在的失败）

