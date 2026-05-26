"""用户管理模块：API Key 认证与权限检查"""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel
import json

from fastapi import Request, HTTPException


class User(BaseModel):
    """用户信息"""
    user_id: str
    name: str
    role: str = "developer"  # developer | admin
    level: int = 1  # 用户级别，用于权限控制和广播策略


class UserManager:
    """极简用户管理：API Key → user_id 映射"""

    def __init__(self, config_path: str = "users.json"):
        self._path = Path(config_path)
        self._users = self._load()

    def _load(self) -> dict[str, dict]:
        """加载用户配置"""
        if not self._path.exists():
            # 默认创建一个默认用户和管理员
            default = {
                "dev_default": {"user_id": "default", "name": "Default User", "role": "developer"},
                "admin": {"user_id": "admin", "name": "Admin", "role": "admin"},
            }
            self._path.write_text(json.dumps(default, indent=2))
            return default
        return json.loads(self._path.read_text())

    def reload(self):
        """重新加载配置（用于热更新）"""
        self._users = self._load()

    def get_user(self, api_key: str) -> Optional[User]:
        """根据 API Key 获取用户"""
        data = self._users.get(api_key)
        if not data:
            return None
        return User(**data)

    def get_current_user(self, request: Request) -> User:
        """从请求获取当前用户

        优先级：
        1. Header X-API-Key
        2. 降级到默认用户（向后兼容）
        """
        api_key = request.headers.get("X-API-Key")

        if api_key:
            user = self.get_user(api_key)
            if user:
                return user

        # 降级：使用默认用户（向后兼容）
        return User(user_id="default", name="Default User", role="developer")

    def is_admin(self, user: User) -> bool:
        """检查是否是管理员"""
        return user.role == "admin"

    def can_delete_workflow(self, user: User, workflow_scope: str, workflow_owner: Optional[str] = None) -> bool:
        """检查是否可以删除 workflow

        规则：
        - admin 可以删除任何 workflow
        - 用户可以删除自己的私有 workflow
        - 不能删除共享 workflow（除非是 admin）
        """
        if self.is_admin(user):
            return True

        if workflow_scope == "private" and workflow_owner == user.user_id:
            return True

        return False


# 全局单例
_user_mgr: Optional[UserManager] = None


def get_user_manager() -> UserManager:
    """获取 UserManager 单例"""
    global _user_mgr
    if _user_mgr is None:
        _user_mgr = UserManager()
    return _user_mgr


def get_current_user(request: Request) -> User:
    """便捷函数：获取当前用户"""
    return get_user_manager().get_current_user(request)