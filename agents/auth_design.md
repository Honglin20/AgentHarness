# 用户认证模块设计文档

## 1. 概述

为用户认证模块提供完整设计，包括注册、登录、密码管理、JWT 令牌、会话管理、OAuth 集成等功能。

### 技术栈
- **框架**: FastAPI
- **ORM**: SQLAlchemy + Alembic
- **令牌**: PyJWT (JWT)
- **密码**: passlib[bcrypt]
- **验证**: pydantic
- **OAuth**: httpx + authlib

---

## 2. 目录结构

```
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                  # 依赖注入（获取当前用户等）
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── auth.py              # 认证路由
│   │       └── users.py             # 用户管理路由
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                # 配置（环境变量）
│   │   ├── security.py              # 密码哈希、JWT 生成/验证
│   │   └── exceptions.py            # 自定义异常
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py                  # User 模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py                  # 认证请求/响应 schema
│   │   └── user.py                  # 用户 schema
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py          # 认证业务逻辑
│   │   ├── user_service.py          # 用户业务逻辑
│   │   └── email_service.py         # 邮件服务（可选）
│   ├── db/
│   │   ├── __init__.py
│   │   └── base.py                  # 数据库会话
│   └── main.py                      # FastAPI 入口
├── alembic/                         # 数据库迁移
│   └── versions/
├── requirements.txt
└── .env
```

---

## 3. 数据模型 (SQLAlchemy)

### User 模型

```python
# app/models/user.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import enum

Base = declarative_base()

class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    avatar_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User {self.username} ({self.email})>"
```

### RefreshToken 模型（可选，用于令牌刷新）

```python
# app/models/refresh_token.py
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="refresh_tokens")
```

---

## 4. 配置 (core/config.py)

```python
# app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "AgentHarness"
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/dbname"

    # JWT
    SECRET_KEY: str  # 必填，从环境变量读取
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 密码策略
    PASSWORD_MIN_LENGTH: int = 8
    BCRYPT_ROUNDS: int = 12

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # OAuth（可选）
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
```

---

## 5. 安全模块 (core/security.py)

```python
# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings
import uuid

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌（JWT）"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),  # 令牌唯一 ID，用于撤销
        "type": "access"
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(data: dict) -> str:
    """创建刷新令牌"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),
        "type": "refresh"
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> dict:
    """解码并验证 JWT 令牌"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise ValueError("Invalid or expired token")
```

---

## 6. Schema (Pydantic)

```python
# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @validator("username")
    def validate_username(cls, v):
        if not v.isalnum() and "_" not in v:
            raise ValueError("Username must be alphanumeric or contain underscores")
        return v

    @validator("password")
    def validate_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)
```

```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID

class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True

class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    avatar_url: Optional[str] = None
```

---

## 7. 服务层

### 认证服务

```python
# app/services/auth_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.services.user_service import UserService
from fastapi import HTTPException, status

class AuthService:
    def __init__(self, db: AsyncSession):
        self.user_service = UserService(db)

    async def register(self, req: RegisterRequest) -> User:
        # 检查用户是否已存在
        existing = await self.user_service.get_by_email(req.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
        existing_username = await self.user_service.get_by_username(req.username)
        if existing_username:
            raise HTTPException(status_code=409, detail="Username already taken")

        user = User(
            email=req.email,
            username=req.username,
            hashed_password=hash_password(req.password)
        )
        return await self.user_service.create(user)

    async def login(self, req: LoginRequest) -> dict:
        user = await self.user_service.get_by_email(req.email)
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated")

        # 更新最后登录时间
        await self.user_service.update_last_login(user)

        # 生成令牌
        token_data = {"sub": str(user.id), "role": user.role.value}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer"
        }
```

### 用户服务

```python
# app/services/user_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from datetime import datetime

class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_last_login(self, user: User) -> None:
        user.last_login_at = datetime.utcnow()
        await self.db.commit()
```

---

## 8. API 路由

```python
# app/api/v1/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, PasswordChangeRequest,
    PasswordResetRequest, PasswordResetConfirm
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.core.security import decode_token, create_access_token
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    service = AuthService(db)
    user = await service.register(req)
    return user

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT 令牌"""
    service = AuthService(db)
    return await service.login(req)

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest):
    """刷新访问令牌"""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Invalid token type")
    token_data = {"sub": payload["sub"], "role": payload.get("role", "user")}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer"
    }

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user

@router.post("/change-password", status_code=204)
async def change_password(
    req: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """修改密码"""
    service = AuthService(db)
    await service.change_password(current_user, req.old_password, req.new_password)

@router.post("/logout", status_code=204)
async def logout(current_user: User = Depends(get_current_user)):
    """登出（客户端应丢弃令牌；服务器端可将来实现令牌黑名单）"""
    # 将来：将当前令牌 JTI 加入黑名单
    pass
```

```python
# app/api/v1/users.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, require_role
from app.schemas.user import UserResponse, UserUpdateRequest
from app.services.user_service import UserService
from app.models.user import User, UserRole
from typing import List
from uuid import UUID

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """（管理员）获取用户列表"""
    service = UserService(db)
    return await service.list_users(skip, limit)

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取指定用户信息（限于本人或管理员）"""
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新当前用户信息"""
    service = UserService(db)
    return await service.update(current_user, req)
```

---

## 9. 依赖注入 (API deps)

```python
# app/api/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.services.user_service import UserService
from app.db.base import get_session

security = HTTPBearer(auto_error=False)

async def get_db() -> AsyncSession:
    """获取数据库会话（在 main.py 中实现为异步生成器）"""
    async with get_session() as session:
        yield session

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """从 JWT 令牌解析当前用户"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user

def require_role(required_role: UserRole):
    """角色验证依赖工厂"""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != required_role and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker
```

---

## 10. 异常处理

```python
# app/core/exceptions.py
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
            }
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": 422,
                "message": "Validation failed",
                "details": exc.errors()
            }
        }
    )
```

---

## 11. 异步数据库会话 (db/base.py)

```python
# app/db/base.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
get_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

---

## 12. 主入口

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import auth, users
from app.core.config import settings
from app.core.exceptions import http_exception_handler, validation_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

# 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 异常处理器
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# 路由
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

---

## 13. 数据库迁移 (Alembic)

```bash
# 初始化
alembic init alembic

# 生成迁移
alembic revision --autogenerate -m "create users table"

# 应用迁移
alembic upgrade head
```

### alembic/env.py 配置

```python
from app.core.config import settings
from app.models.user import Base

target_metadata = Base.metadata

def run_migrations_offline():
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

def run_migrations_online():
    connectable = create_engine(url.replace("+asyncpg", ""))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

---

## 14. 安全策略总结

| 项目 | 策略 |
|------|------|
| 密码存储 | bcrypt (12 rounds) |
| 令牌格式 | JWT (HS256) |
| Access Token 有效期 | 30 分钟 |
| Refresh Token 有效期 | 7 天 |
| 令牌刷新 | 使用 Refresh Token 获取新 Access Token |
| 密码强度 | ≥8 位，含大小写字母和数字 |
| 速率限制 | 登录接口建议使用 slowapi 限制 5 次/分钟 |
| CORS | 限定允许的源站 |

---

## 15. 依赖清单 (requirements.txt)

```
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy[asyncio]==2.0.25
asyncpg==0.29.0
alembic==1.13.1
pydantic==2.5.3
pydantic-settings==2.1.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.1.2
email-validator==2.1.0
httpx==0.26.0
authlib==1.3.0
slowapi==0.1.9
python-multipart==0.0.6
```

---

## 16. 后续可扩展功能

- [ ] OAuth2 社交登录（GitHub, Google, WeChat）
- [ ] 邮箱验证（发送验证邮件）
- [ ] 两步验证（TOTP）
- [ ] 会话管理（查看/撤销活跃会话）
- [ ] 令牌黑名单（Redis 存储已撤销的 JTI）
- [ ] 操作审计日志
- [ ] 管理员后台用户管理界面
