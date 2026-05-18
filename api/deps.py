"""
FastAPI 依赖注入
提供 get_db, get_current_user 等常用依赖
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from api.database import SessionLocal
from config import SECRET_KEY, JWT_ALGORITHM

security = HTTPBearer(auto_error=False)


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """获取当前登录用户（可选认证，未登录返回默认用户 ID=1）"""
    if credentials:
        try:
            import jwt
            payload = jwt.decode(
                credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM]
            )
            user_id = payload.get("sub")
            if user_id:
                from api.models import User
                user = db.query(User).filter(User.id == int(user_id)).first()
                if user:
                    return user
        except Exception:
            pass

    # 默认用户（开发模式）
    from api.models import User
    user = db.query(User).filter(User.id == 1).first()
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user
