"""迁移脚本：将现有 workflows 迁移到新的用户隔离结构

运行方式：
    python scripts/migrate_to_user_isolated.py
"""

import shutil
from pathlib import Path

# 工作流根目录
WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

# 创建目标目录
SHARED_WORKFLOWS = WORKFLOWS_DIR / "_shared" / "workflows"
USERS_DIR = WORKFLOWS_DIR / "users"

SHARED_WORKFLOWS.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(exist_ok=True)

print("=== Multi-Developer Isolation Migration ===")
print(f"Workflows root: {WORKFLOWS_DIR}")
print(f"Shared workflows: {SHARED_WORKFLOWS}")
print(f"Users directory: {USERS_DIR}")
print()

# 统计
migrated_count = 0
skipped_count = 0

# 遍历 workflows 根目录
for wf_dir in sorted(WORKFLOWS_DIR.iterdir()):
    if wf_dir.name.startswith("_"):
        # 跳过 _shared 等系统目录
        continue

    if not wf_dir.is_dir():
        continue

    # 检查是否有 workflow.json
    wf_json = wf_dir / "workflow.json"
    if not wf_json.exists():
        continue

    print(f"Processing: {wf_dir.name}")

    # 检查是否已经在 shared 目录
    shared_path = SHARED_WORKFLOWS / wf_dir.name
    if shared_path.exists():
        print(f"  → Already in shared, skipping")
        skipped_count += 1
        continue

    # 移动到共享目录
    try:
        shutil.move(str(wf_dir), str(shared_path))
        print(f"  → Moved to shared")
        migrated_count += 1
    except Exception as e:
        print(f"  → Error: {e}")

print()
print("=== Migration Summary ===")
print(f"Migrated: {migrated_count}")
print(f"Skipped: {skipped_count}")
print()
print("Next steps:")
print("1. Review users.json to configure API Keys")
print("2. Create user directories for private workflows")
print("3. Test with curl:")
print("   curl -H 'X-API-Key: dev_alice' http://localhost:8000/api/workflows/definitions")