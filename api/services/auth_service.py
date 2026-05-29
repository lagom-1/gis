"""
验证码服务
- 生成 6 位数字验证码
- 存储到内存（生产环境应使用 Redis）
"""

import random
import time
import logging

logger = logging.getLogger(__name__)

# 验证码存储（生产环境应使用 Redis）
_code_store: dict[str, tuple[str, float]] = {}

CODE_EXPIRE_SECONDS = 300  # 5 分钟过期


def generate_code(email: str) -> str:
    """生成并存储验证码"""
    code = f"{random.randint(0, 999999):06d}"
    _code_store[email] = (code, time.time() + CODE_EXPIRE_SECONDS)
    logger.info(f"验证码已生成: {email} -> {code}")
    return code


def verify_code(email: str, code: str) -> bool:
    """验证验证码"""
    stored = _code_store.get(email)
    if not stored:
        return False

    stored_code, expire_time = stored
    if time.time() > expire_time:
        del _code_store[email]
        return False

    if stored_code != code:
        return False

    del _code_store[email]
    return True
