"""Test two-message flow in same conversation"""
import requests
import json
import time

BASE = "http://localhost:8000"

# Create conversation
r = requests.post(f"{BASE}/api/conversations", json={"title": "state persistence test"})
conv = r.json()
conv_id = conv["id"]
print(f"Created conversation: {conv_id}")

# Message 1: simple tool call
print("\n=== Message 1: set_current_dataset ===")
r1 = requests.post(
    f"{BASE}/api/conversations/{conv_id}/messages/stream",
    json={"content": "请用 set_current_dataset 工具设置当前数据集路径为 D:/opengis/workspace/outputs/test.tif"},
    stream=True,
    timeout=120,
)
print(f"Status: {r1.status_code}")
for line in r1.iter_lines(decode_unicode=True):
    if line:
        print(f"  {line[:200]}")
print("Message 1 done")

# Check state in DB
time.sleep(1)
print("\n=== Checking DB state ===")
import sys
sys.path.insert(0, "D:/opengis")
from api.database import SessionLocal, create_tables
from api.services.conversation_service import load_conversation_state
create_tables()
db = SessionLocal()
state = load_conversation_state(db, conv_id)
print(f"State from DB: current_dataset={state.get('current_dataset') if state else 'NO STATE'}")
db.close()

# Message 2: try to use the persisted state
print("\n=== Message 2: check state ===")
r2 = requests.post(
    f"{BASE}/api/conversations/{conv_id}/messages",
    json={"content": "当前的数据集路径是什么？请用 inspect_raster 检查一下"},
    timeout=120,
)
result = r2.json()
print(f"Result: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
print("Done")
