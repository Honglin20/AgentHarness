#!/usr/bin/env python3
"""用户管理命令行工具

用法:
    python manage_users.py list
    python manage_users.py create <user_id> <name> [--role developer|admin] [--level 1-11]
    python manage_users.py update <user_id> [--name NAME] [--role ROLE] [--level LEVEL]
    python manage_users.py delete <user_id>
    python manage_users.py regenerate <user_id>
"""

import argparse
import json
import random
import string
from pathlib import Path


USERS_FILE = Path(__file__).parent.parent / "users.json"


def load_users() -> dict:
    """加载用户配置"""
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text())


def save_users(users: dict) -> None:
    """保存用户配置"""
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False))


def generate_api_key(length: int = 24) -> str:
    """生成随机 API Key"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def cmd_list(args) -> None:
    """列出所有用户"""
    users = load_users()

    if not users:
        print("暂无用户")
        return

    print(f"\n{'API Key':<30} {'User ID':<15} {'Name':<20} {'Role':<12} {'Level':<6}")
    print("-" * 85)

    for api_key, data in users.items():
        print(f"{api_key:<30} {data['user_id']:<15} {data['name']:<20} {data['role']:<12} {data.get('level', 1):<6}")

    print(f"\n共 {len(users)} 个用户")


def cmd_create(args) -> None:
    """创建新用户"""
    users = load_users()

    # 检查 user_id 是否已存在
    for api_key, data in users.items():
        if data.get("user_id") == args.user_id:
            print(f"错误: 用户 ID '{args.user_id}' 已存在 (API Key: {api_key})")
            return

    # 生成 API Key
    if not args.api_key:
        api_key = generate_api_key()
        # 检查是否重复
        while api_key in users:
            api_key = generate_api_key()
    else:
        if args.api_key in users:
            print(f"错误: API Key '{args.api_key}' 已存在")
            return
        api_key = args.api_key

    # 创建用户
    users[api_key] = {
        "user_id": args.user_id,
        "name": args.name,
        "role": args.role or "developer",
        "level": args.level or 1,
    }

    save_users(users)
    print(f"✓ 用户创建成功")
    print(f"  API Key: {api_key}")
    print(f"  User ID: {args.user_id}")
    print(f"  Name: {args.name}")
    print(f"  Role: {args.role or 'developer'}")
    print(f"  Level: {args.level or 1}")


def cmd_update(args) -> None:
    """更新用户"""
    users = load_users()

    # 查找用户
    target_api_key = None
    for api_key, data in users.items():
        if data.get("user_id") == args.user_id:
            target_api_key = api_key
            break

    if not target_api_key:
        print(f"错误: 用户 ID '{args.user_id}' 不存在")
        return

    # 更新字段
    if args.name:
        users[target_api_key]["name"] = args.name
    if args.role:
        if args.role not in ("developer", "admin"):
            print("错误: role 必须是 'developer' 或 'admin'")
            return
        users[target_api_key]["role"] = args.role
    if args.level is not None:
        users[target_api_key]["level"] = args.level

    save_users(users)
    print(f"✓ 用户 '{args.user_id}' 更新成功")


def cmd_delete(args) -> None:
    """删除用户"""
    users = load_users()

    # 查找用户
    target_api_key = None
    for api_key, data in users.items():
        if data.get("user_id") == args.user_id:
            target_api_key = api_key
            break

    if not target_api_key:
        print(f"错误: 用户 ID '{args.user_id}' 不存在")
        return

    # 防止删除最后一个 admin
    if users[target_api_key].get("role") == "admin":
        admin_count = sum(1 for d in users.values() if d.get("role") == "admin")
        if admin_count <= 1:
            print("错误: 不能删除最后一个管理员用户")
            return

    # 确认
    print(f"即将删除用户 '{args.user_id}' (API Key: {target_api_key})")
    confirm = input("确认删除? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("已取消")
        return

    del users[target_api_key]
    save_users(users)
    print(f"✓ 用户 '{args.user_id}' 已删除")


def cmd_regenerate(args) -> None:
    """重新生成 API Key"""
    users = load_users()

    # 查找用户
    target_api_key = None
    for api_key, data in users.items():
        if data.get("user_id") == args.user_id:
            target_api_key = api_key
            break

    if not target_api_key:
        print(f"错误: 用户 ID '{args.user_id}' 不存在")
        return

    old_api_key = target_api_key
    user_data = users.pop(old_api_key)

    # 生成新 API Key
    new_api_key = generate_api_key()
    while new_api_key in users:
        new_api_key = generate_api_key()

    users[new_api_key] = user_data
    save_users(users)

    print(f"✓ API Key 已更新")
    print(f"  用户: {args.user_id}")
    print(f"  旧 Key: {old_api_key}")
    print(f"  新 Key: {new_api_key}")


def main():
    parser = argparse.ArgumentParser(description="用户管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # list
    subparsers.add_parser("list", help="列出所有用户")

    # create
    create_parser = subparsers.add_parser("create", help="创建新用户")
    create_parser.add_argument("user_id", help="用户 ID")
    create_parser.add_argument("name", help="用户名称")
    create_parser.add_argument("--api-key", help="指定 API Key（不指定则自动生成）")
    create_parser.add_argument("--role", choices=["developer", "admin"], help="用户角色")
    create_parser.add_argument("--level", type=int, help="用户级别 (1-11)")

    # update
    update_parser = subparsers.add_parser("update", help="更新用户")
    update_parser.add_argument("user_id", help="用户 ID")
    update_parser.add_argument("--name", help="用户名称")
    update_parser.add_argument("--role", choices=["developer", "admin"], help="用户角色")
    update_parser.add_argument("--level", type=int, help="用户级别 (1-11)")

    # delete
    subparsers.add_parser("delete", help="删除用户").add_argument("user_id", help="用户 ID")

    # regenerate
    subparsers.add_parser("regenerate", help="重新生成 API Key").add_argument("user_id", help="用户 ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "list": cmd_list,
        "create": cmd_create,
        "update": cmd_update,
        "delete": cmd_delete,
        "regenerate": cmd_regenerate,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()