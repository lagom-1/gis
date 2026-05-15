"""
认证路由
- POST /api/auth/register  用户注册
- POST /api/auth/login     用户登录，返回 JWT
- GET  /api/auth/me        获取当前用户信息
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

import config
from api.database import get_db
from api.models import (
    MessageResponse,
    TokenResponse,
    User,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["认证"])

# ── 工具函数 ──────────────────────────────────────────────

def hash_password(password: str) -> str:
    """生成密码哈希（使用 SHA-256 + 盐值）"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{pwd_hash}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        salt, stored_hash = hashed_password.split(":")
        pwd_hash = hashlib.sha256(f"{salt}{plain_password}".encode()).hexdigest()
        return pwd_hash == stored_hash
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=config.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


# ── 认证依赖 ──────────────────────────────────────────────

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security_scheme = HTTPBearer(auto_error=False)

# 默认用户 ID（无认证时使用，开发模式）
DEFAULT_USER_ID = 1


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 Authorization header 解析 JWT 并返回用户对象"""
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """可选认证：有 token 时解析，无 token 时返回默认用户（开发模式）"""
    if credentials is None:
        user = db.query(User).filter(User.id == DEFAULT_USER_ID).first()
        if user is None:
            # 自动创建默认用户
            user = User(
                id=DEFAULT_USER_ID,
                username="default",
                email="default@opengis.local",
                password_hash="no-login",
                credits=99999,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    try:
        payload = jwt.decode(credentials.credentials, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str:
            user = db.query(User).filter(User.id == int(user_id_str)).first()
            if user:
                return user
    except (JWTError, ValueError):
        pass

    # token 无效时回退到默认用户
    user = db.query(User).filter(User.id == DEFAULT_USER_ID).first()
    return user or User(id=DEFAULT_USER_ID, username="default", email="default@opengis.local", password_hash="no-login", credits=99999)


# ── 端点 ──────────────────────────────────────────────────

@router.post("/register", response_model=MessageResponse, summary="用户注册")
async def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """注册新用户"""
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(
        (User.username == request.username) | (User.email == request.email)
    ).first()
    if existing_user:
        if existing_user.username == request.username:
            raise HTTPException(status_code=400, detail="用户名已被注册")
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 创建用户
    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        credits=1000,  # 新用户赠送 1000 积分
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return MessageResponse(success=True, message=f"注册成功，欢迎 {user.username}！已赠送 1000 积分。")


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """用户登录，返回 JWT Token"""
    # 支持用户名或邮箱登录
    user = db.query(User).filter(
        (User.username == request.username) | (User.email == request.username)
    ).first()

    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=timedelta(minutes=config.JWT_EXPIRE_MINUTES),
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=config.JWT_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_me(current_user: User = Depends(_get_current_user)):
    """获取当前已认证用户的信息"""
    return current_user
