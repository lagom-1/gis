"""检查任务的输出文件路径"""
import sys
sys.path.insert(0, '.')

from api.database import get_db
from api.models import Task

db = next(get_db())

# 查找所有任务
tasks = db.query(Task).all()
for task in tasks:
    print(f"任务 #{task.id}: {task.input_text[:50]}")
    if task.output_files:
        print(f"  输出文件类型: {type(task.output_files)}")
        if isinstance(task.output_files, dict):
            for name, path in task.output_files.items():
                print(f"    {name}: {path}")
        elif isinstance(task.output_files, list):
            for f in task.output_files:
                print(f"    {f}")
    print()
