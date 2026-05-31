"""
测试北京市朝阳区2020-2023年每年2月LST完整链路
"""
from api.database import SessionLocal
from api.services.conversation_service import create_conversation
from api.models import User

db = SessionLocal()
user = db.query(User).first()
if not user:
    user = User(id=1, username='test', hashed_password='test')
    db.add(user)
    db.commit()

conv = create_conversation(db, user_id=user.id, title='北京市朝阳区LST测试')
print(f'创建会话: {conv.id}')
