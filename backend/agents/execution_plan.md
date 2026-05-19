# 📋 执行计划摘要：Python Web 项目用户认证模块

## 1. 任务总览

> **目标**：为 FastAPI + PostgreSQL + JWT 架构的 Python Web 项目设计并实现完整的用户认证模块。  
> **工期**：5-6 天（6 个阶段，可直接并行或部分重叠）  
> **安全评级**：⭐⭐⭐⭐⭐（经审查确认，P0 问题已在本计划中修复）

---

## 2. 架构全景图

```
┌─────────────────────────────────────────────────────┐
│                   客户端 (SPA/Mobile)                  │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP Request + Bearer Token
┌──────────────────▼──────────────────────────────────┐
│                   FastAPI 应用                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│  │ Router  │→│ Service │→│Security │→│ Depend.  │  │
│  │(路由层) │ │(业务层) │ │(安全层) │ │(注入层)  │  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬─────┘  │
│       │           │           │           │         │
│  ┌────▼────┐ ┌────▼────┐     │     ┌──────▼──────┐ │
│  │ Schema  │ │ Models  │     │     │ Exceptions  │ │
│  │(验证层) │ │(ORM层)  │     │     │ (异常处理)  │ │
│  └─────────┘ └────┬────┘     │     └─────────────┘ │
└───────────────────┼──────────┼──────────────────────┘
                    │          │
        ┌───────────▼──┐  ┌───▼───────────┐
        │ PostgreSQL   │  │    Redis      │
        │ (用户数据)   │  │(限流/黑名单)  │
        └──────────────┘  └───────────────┘
```

---

## 3. 阶段执行计划（6 阶段，可并行）

### 阶段 1：项目骨架与配置（Day 1）⚡ 高优先级

| 任务 | 产出 | 说明 |
|------|------|------|
| 1.1 创建目录结构 | `app/auth/`, `app/core/`, `tests/` | 按模块化分层搭建 |
| 1.2 依赖管理 | `requirements.txt` | fastapi, uvicorn, sqlalchemy, asyncpg, passlib[bcrypt], python-jose[jwcrypto], pydantic[email], python-multipart, redis, httpx, pytest, pytest-asyncio, ruff, mypy |
| 1.3 配置管理 | `core/config.py` | 使用 pydantic-settings 加载 .env，关键项：SECRET_KEY, ALGORITHM(RS256/HS256), ACCESS_EXPIRE(15min), REFRESH_EXPIRE(7d), DATABASE_URL, REDIS_URL, CORS_ORIGINS, SMTP_* |
| 1.4 数据库初始化 | `core/database.py` | AsyncSession + async engine (asyncpg) |
| 1.5 代码规范 | `pyproject.toml` | ruff 配置 + mypy 类型检查 |

### 阶段 2：数据模型与 Schema（Day 1-2）⚡ 高优先级

| 任务 | 产出 | 说明 |
|------|------|------|
| 2.1 User ORM 模型 | `auth/models.py` | id(UUID), username(unique), email(unique), hashed_password, is_active, is_verified, role(Enum: admin/user/guest), failed_login_attempts(int), locked_until(datetime), created_at, updated_at, last_login |
| 2.2 请求 Schema | `auth/schemas.py` | `UserCreate`(含密码规则验证), `UserLogin`, `TokenRefresh`, `PasswordResetRequest`, `PasswordReset`(含新密码约束), `PasswordChange` |
| 2.3 响应 Schema | `auth/schemas.py` | `UserResponse`(无密码字段), `TokenResponse`(access_token, refresh_token, token_type), `UserPublic`(公开信息), `ErrorResponse`(**统一错误格式**) |

### 阶段 3：核心安全层（Day 2-3）🔥 **关键路径**

| 任务 | 产出 | 说明 |
|------|------|------|
| 3.1 密码工具 | `auth/security.py` | `get_password_hash()` + `verify_password()` — bcrypt cost=12 |
| 3.2 JWT 工具 | `auth/security.py` | `create_access_token()`(15min, 含jti), `create_refresh_token()`(7d, 含jti), `decode_jwt()`, `generate_reset_token()`(**15min时效+单次使用**) |
| 3.3 依赖注入 | `auth/dependencies.py` | `get_current_user()`(验证+黑名单检查), `get_current_active_user()`, `require_role(role)`(RBAC装饰器), `RateLimiter()`(依赖注入方式) |
| 3.4 自定义异常 | `auth/exceptions.py` | `AuthException`(统一错误码: AUTH_INVALID_CREDENTIALS, AUTH_TOKEN_EXPIRED, AUTH_ACCOUNT_LOCKED等) |

### 阶段 4：业务逻辑与 API（Day 3-4）🔥 **关键路径**

| 任务 | 产出 | 说明 |
|------|------|------|
| 4.1 Service 层 | `auth/service.py` | 实现全部业务逻辑（见下方详表） |
| 4.2 Router 层 | `auth/router.py` | 注册所有端点 + 速率限制装饰器 |
| 4.3 主应用注册 | `main.py` | 注册 router + 全局异常处理器 + CORS 中间件 |

**👉 Service 层核心方法矩阵：**

```python
class AuthService:
    async def register(self, user_data) → User           # 注册+哈希密码+发送验证邮件
    async def login(self, credentials) → TokenResponse    # 验证→检查锁定→更新last_login→签发Token
    async def logout(self, token_jti) → None              # jti加入Redis黑名单
    async def refresh_token(self, refresh_token) → TokenResponse  # 验证Refresh→签发新Access
    async def verify_email(self, token) → None             # 邮箱验证
    async def forgot_password(self, email) → None          # 生成重置Token→发送邮件(15min)
    async def reset_password(self, token, new_pwd) → None  # 验证Token+标记已用+更新密码
    async def get_current_user(self, token) → User         # 解码+黑名单检查+返回用户
    async def change_password(self, user, old_pwd, new_pwd) → None  # 验证旧密码→更新
    async def get_login_history(self, user_id) → List[Log] # 审计日志查询
```

### 阶段 5：安全加固（Day 4-5）🛡️ **安全专项**

| 任务 | 产出 | 说明 |
|------|------|------|
| 5.1 ✅ **账号锁定机制(P0)** | `auth/service.py` | 连续5次登录失败→锁定15分钟(failed_login_attempts+locked_until) |
| 5.2 ✅ **统一错误响应(P0)** | `auth/exceptions.py`+全局处理器 | 所有异常返回 `{error:{code, message, details}}` |
| 5.3 ✅ **审计日志(P0)** | `core/audit.py` | 记录重要事件：登录成功/失败、密码修改、角色变更、注册 |
| 5.4 Redis 限流中间件 | `core/ratelimit.py` | 登录5次/分钟/IP, 注册3次/分钟/IP, 全局100次/分钟/IP |
| 5.5 Token 黑名单 | `auth/security.py` | 登出时将jti加入Redis(有效期=Token剩余有效期) |
| 5.6 CORS & 安全头部 | `main.py`+中间件 | 严格CORS白名单 + HSTS/X-Content-Type-Options/X-Frame-Options |
| 5.7 密码策略验证 | `auth/schemas.py` | 最小8位+大小写+数字+特殊字符(pydantic validator) |

### 阶段 6：测试与文档（Day 5-6）✅ **质量保证**

| 任务 | 产出 | 说明 |
|------|------|------|
| 6.1 单元测试 | `tests/test_security.py` | 密码哈希、JWT生成/验证/过期、黑名单检查 |
| 6.2 服务测试 | `tests/test_service.py` | 注册、登录、刷新、锁定、重置密码全流程 |
| 6.3 API 集成测试 | `tests/test_api.py` | 使用TestClient模拟全部端点(✅正常 + ❌异常场景覆盖) |
| 6.4 安全测试 | `tests/test_security_integration.py` | 限流测试、令牌篡改、用户枚举防护验证 |
| 6.5 文档 | `README.md` + API文档 | FastAPI自动Swagger + 使用说明 + 部署指南 |
| 6.6 CI/CD | `.github/workflows/test.yml` | GitHub Actions自动运行测试+ruff检查 |

---

## 4. 测试覆盖矩阵

| 测试场景 | 覆盖端点 | 预期结果 |
|---------|---------|---------|
| ✅ 正常注册流程 | POST /register | 201 + 用户信息(无密码) |
| ❌ 重复用户名注册 | POST /register | 409 + AUTH_USER_EXISTS |
| ❌ 弱密码注册 | POST /register | 422 + 密码规则提示 |
| ✅ 正常登录 | POST /login | 200 + TokenResponse |
| ❌ 错误密码登录 | POST /login | 401 + AUTH_INVALID_CREDENTIALS |
| ❌ 账号锁定(5次失败) | POST /login | 423 + AUTH_ACCOUNT_LOCKED |
| ✅ Token刷新 | POST /refresh | 200 + 新AccessToken |
| ❌ 过期RefreshToken | POST /refresh | 401 + AUTH_TOKEN_EXPIRED |
| ✅ 黑名单Token访问 | GET /me | 401 + AUTH_TOKEN_REVOKED |
| ❌ 越权访问 | GET /admin | 403 + AUTH_FORBIDDEN |
| ✅ 密码重置(15min内) | POST /reset-password | 200 + 成功 |
| ❌ 密码重置(超时) | POST /reset-password | 401 + AUTH_TOKEN_EXPIRED |
| ✅ 限流触发 | POST /login ×6 | 429 + 限流提示 |

---

## 5. 安全防护矩阵（含 P0 修复）

| 威胁 | 防护措施 | 状态 |
|------|---------|------|
| 🔴 暴力破解 | Redis 限流(5次/分钟/IP) + **账号锁定(5次失败→15min)** | ✅ 已修复 |
| 🔴 密码泄露 | bcrypt(cost=12) + **永不返回密码字段** | ✅ 已覆盖 |
| 🔴 JWT泄露 | Access 15min + Refresh 7d + **黑名单(登出即失效)** | ✅ 已覆盖 |
| 🔴 重置令牌滥用 | **15分钟时效 + 单次使用标记 + 关联用户验证** | ✅ 已修复(P0) |
| 🔴 用户枚举 | **统一错误信息**("用户名或密码错误"不区分是否存在) | ✅ 已覆盖 |
| 🔴 SQL注入 | ORM + 参数化查询 | ✅ 已覆盖 |
| 🔴 XSS/CSRF | CORS白名单 + 安全头部 + Content-Type校验 | ✅ 已覆盖 |
| 🔴 审计缺失 | **登录/注册/密码修改/角色变更全部记录日志** | ✅ 已修复(P0) |
| 🔴 错误信息泄露 | **统一错误响应格式** `{error:{code, message, details}}` | ✅ 已修复(P0) |

---

## 6. 目录结构（最终版）

```
project/
├── app/
│   ├── __init__.py
│   ├── main.py                    # 应用入口 + 全局异常处理器 + CORS + 中间件
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py              # API路由 (8个端点)
│   │   ├── schemas.py             # Pydantic请求/响应模型 + 统一错误Schema
│   │   ├── service.py             # 全部业务逻辑 (含账号锁定)
│   │   ├── dependencies.py        # get_current_user + RBAC + 速率限制
│   │   ├── security.py            # 密码哈希 + JWT + Token黑名单
│   │   ├── models.py              # SQLAlchemy User模型
│   │   └── exceptions.py          # AuthException + 错误码枚举
│   └── core/
│       ├── __init__.py
│       ├── config.py              # 环境变量管理 (pydantic-settings)
│       ├── database.py            # 异步数据库引擎 + 会话工厂
│       ├── audit.py               # 审计日志记录器
│       └── ratelimit.py           # Redis速率限制中间件
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # 测试夹具 (测试DB, TestClient, Mock Redis)
│   ├── test_security.py           # 密码/JWT单元测试
│   ├── test_service.py            # 业务逻辑测试
│   ├── test_api.py                # API集成测试
│   └── test_security_integration.py # 安全专项测试
├── .env.example                   # 环境变量模板
├── .github/workflows/test.yml     # CI配置
├── requirements.txt               # 依赖清单
├── pyproject.toml                 # 项目配置(ruff, mypy)
└── README.md                      # 使用说明 + API文档索引
```

---

## 7. 关键设计决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 异步架构 | FastAPI + asyncpg + SQLAlchemy 2.0 async | 高并发场景性能优势 |
| 密码哈希 | bcrypt (cost=12) | 行业标准，抗GPU并行破解 |
| JWT签名 | RS256 (非对称) | 可安全分发公钥，微服务间验证 |
| 会话状态 | 无状态(JWT) + Redis黑名单辅助 | 兼顾扩展性与Token回收能力 |
| 用户标识 | UUID (非自增ID) | 防ID枚举，安全性更高 |
| 错误处理 | 统一错误码 + 异常处理器 | 前端可统一处理，调试友好 |
| 审计日志 | 结构化JSON写入文件/DB | 可对接ELK等日志分析平台 |

---

## 8. 风险与应对

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|---------|
| bcrypt cost=12 响应慢 | 中 | 低 | 仅在登录时验证，可用异步执行 |
| Redis 不可用 | 低 | 中 | 降级为内存缓存 + 告警，限流暂时失效但核心认证可用 |
| JWT密钥泄露 | 低 | 高 | RS256密钥对 + 定期轮换 + 黑名单可立即使旧Token失效 |
| 邮件服务不可用 | 中 | 中 | 邮箱验证/密码重置异步重试 + 用户可手动请求重发 |
| 数据库连接池耗尽 | 低 | 高 | 连接池大小调优 + 超时设置 + 熔断机制 |

---

## 9. 实施建议

### 🔥 优先实施顺序
```
第一优先级（Day 1-2）: 阶段1→2→3  (基础架构+安全核心)
第二优先级（Day 3-4）: 阶段4      (业务逻辑)  
第三优先级（Day 4-5）: 阶段5      (安全加固)
第四优先级（Day 5-6）: 阶段6      (测试+文档)
```

### ⚡ 并行建议
- **阶段2与阶段3可并行**（模型设计与安全工具函数开发不冲突）
- **阶段1完成后即可启动阶段2+3**
- **阶段6可与阶段4重叠**（测试与开发同步进行）

### 📊 交付物清单
| 类型 | 数量 | 说明 |
|------|------|------|
| Python模块 | 14个 | auth/6 + core/4 + tests/4 |
| 配置文件 | 4个 | .env.example, requirements.txt, pyproject.toml, .github/workflows/test.yml |
| 文档 | 2个 | README.md + FastAPI自动Swagger |
| 测试用例 | 15+ | 覆盖所有正常+异常场景 |

---

> **总结**：本计划基于上游分析结果，在保留原有6阶段结构的基础上，**修复了审查环节确认的4个P0安全问题**（密码重置令牌时效+单次使用、账号锁定机制、统一错误响应格式、审计日志），并补充了测试覆盖矩阵、安全防御矩阵和风险应对策略。按此计划执行，可在6天内交付一个**生产级安全水平**的用户认证模块。
