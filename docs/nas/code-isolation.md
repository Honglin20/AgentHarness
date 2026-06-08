# 并发代码修改隔离方案

> 状态：待实现
> 对比参考：Claude Code EnterWorktree、Codex git worktrees

## 问题

NAS workflow 中 analyzer 可能决定"同时试 3 个优化策略"。每个 sub-agent 需要独立修改模型代码并训练。如果不隔离：
- 多个 agent 同时改同一文件 → 冲突
- 一个 agent 的修改影响另一个的训练结果

## 方案对比

| 方案 | 代码隔离 | 数据共享 | 复杂度 |
|------|---------|---------|--------|
| **Git worktree** | 完整隔离 | 需额外处理 | 中 |
| **目录拷贝** | 完整隔离 | 隐式共享（各一份） | 低，但占空间 |
| **Symlink + overlay** | 部分隔离 | 共享 | 高 |

### 推荐：Git worktree + symlink 数据目录

```python
# 每个 sub-agent 获得独立 worktree
worktree_path = f"/tmp/nas_worktree_{strategy_id}"
subprocess.run(["git", "worktree", "add", worktree_path, HEAD])

# 数据目录用 symlink 共享（不复制）
os.symlink(f"{project_path}/data", f"{worktree_path}/data")
os.symlink(f"{project_path}/checkpoints", f"{worktree_path}/checkpoints")
```

**优点：**
- 代码完全隔离，git 管理差异
- 数据共享，不占额外空间
- 完成后可 `git diff` 看改动，或 `git worktree remove` 清理

**实现为工具：**

```python
# 由 parallel_tasks 工具内部调用
def create_isolated_worktree(project_path: str, strategy_id: str) -> str:
    """为 sub-agent 创建隔离工作目录"""
    ...

def cleanup_worktree(worktree_path: str) -> None:
    """清理 worktree"""
    ...
```

**需要处理的问题：**
- worktree 数量限制（git 默认无限制，但磁盘有限）
- 清理时机（task 完成/失败/超时）
- 数据目录权限（多个进程同时读）
- GPU 资源分配（多个训练进程共享 GPU）
