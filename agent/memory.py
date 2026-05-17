"""
记忆管理模块 - 会话记忆、用户偏好、运行日志
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DEFAULT_PREFERENCES, MEMORY_PATH, PREFERENCES_PATH, RUNS_DIR


@dataclass
class ToolEvent:
    step: int
    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any]
    reason: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class SessionMemory:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str = ""
    current_dataset: Optional[str] = None
    source_dataset: Optional[str] = None
    product_type: Optional[str] = None
    current_output: Optional[str] = None
    active_plan: List[str] = field(default_factory=list)
    completed_steps: List[str] = field(default_factory=list)
    known_facts: Dict[str, Any] = field(default_factory=dict)
    map_style: Dict[str, Any] = field(default_factory=dict)
    recent_events: List[ToolEvent] = field(default_factory=list)

    def to_prompt_context(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "goal": self.goal,
            "current_dataset": self.current_dataset,
            "source_dataset": self.source_dataset,
            "product_type": self.product_type,
            "current_output": self.current_output,
            "active_plan": self.active_plan[-8:],
            "completed_steps": self.completed_steps[-12:],
            "known_facts": self.known_facts,
            "map_style": self.map_style,
            "recent_events": [asdict(e) for e in self.recent_events[-6:]],
        }


class MemoryStore:
    def __init__(self, memory_path: Path | None = None, preferences_path: Path | None = None) -> None:
        self.memory_path = memory_path or MEMORY_PATH
        self.preferences_path = preferences_path or PREFERENCES_PATH
        self.session = self._load_session()
        self.preferences = self._load_preferences()

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_session(self) -> SessionMemory:
        raw = self._load_json(self.memory_path, {})
        if not raw:
            return SessionMemory()
        recent_events = [ToolEvent(**e) for e in raw.get("recent_events", [])]
        raw["recent_events"] = recent_events
        return SessionMemory(**raw)

    def _load_preferences(self) -> Dict[str, Any]:
        prefs = self._load_json(self.preferences_path, {})
        merged = dict(DEFAULT_PREFERENCES)
        merged.update(prefs)
        return merged

    def save(self) -> None:
        serializable = asdict(self.session)
        self._save_json(self.memory_path, serializable)
        self._save_json(self.preferences_path, self.preferences)

    def start_new_task(self, goal: str) -> None:
        """
        开始新任务时重置执行步数相关状态。

        current_dataset / source_dataset / known_facts 保留，
        因为用户经常说"将刚刚的结果做时序动画"，需要跨任务上下文。
        map_style 保留 - 用户视觉偏好，跨任务继承。
        """
        self.session.task_id = uuid.uuid4().hex[:12]
        self.session.goal = goal
        self.session.active_plan = []
        self.session.completed_steps = []
        self.session.recent_events = []
        # 保留：current_dataset, source_dataset, known_facts, product_type, current_output
        # 保留：map_style
        self.save()

    def append_event(self, step: int, tool: str, args: Dict[str, Any], result: Dict[str, Any], reason: str = "") -> None:
        self.session.recent_events.append(ToolEvent(step=step, tool=tool, args=args, result=result, reason=reason))
        self.session.recent_events = self.session.recent_events[-20:]
        self._update_from_result(tool, args, result)
        self.save()

    def _update_from_result(self, tool: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        # 数据集路径跟踪
        if tool in {"set_current_dataset", "search_local_files", "inspect_raster", "run_lst",
                     "gee_download_landsat_sca", "gee_download_monthly_lst"}:
            path = result.get("selected_path") or result.get("path") or result.get("output_tif") or args.get("path")
            if path:
                self.session.current_dataset = path
                if not self.session.source_dataset:
                    self.session.source_dataset = path

        # GEE 批量下载工具：记录输出目录和质量摘要，防止 LLM 重复下载
        if tool in {"gee_download_yearly_lst", "gee_download_multi_year_lst"}:
            if result.get("output_dir"):
                self.session.current_dataset = result["output_dir"]
                self.session.known_facts["output_dir"] = result["output_dir"]
            if result.get("success_count") is not None:
                self.session.known_facts["download_summary"] = {
                    "tool": tool,
                    "year": args.get("year"),
                    "months": args.get("months"),
                    "success_count": result.get("success_count"),
                    "quality_summary": result.get("quality_summary"),
                }

        # 元数据跟踪
        meta = result.get("metadata") or {}
        if meta.get("product_type"):
            self.session.product_type = meta.get("product_type")
        if result.get("output_png"):
            self.session.current_output = result.get("output_png")
        if result.get("output_path"):
            self.session.current_output = result.get("output_path")
        if result.get("inspection_summary"):
            self.session.known_facts["inspection_summary"] = result["inspection_summary"]
        if result.get("metadata"):
            self.session.known_facts["last_metadata"] = result["metadata"]

        # 时间序列工具：记录已生成的文件
        if tool in {"generate_lst_timelapse_local", "generate_lst_timelapse"}:
            if result.get("output_gif"):
                self.session.current_output = result["output_gif"]
                self.session.known_facts["timelapse_generated"] = True
            if result.get("output_path"):
                self.session.current_output = result.get("output_path")

        # 专题图：记录已生成的图片
        if tool == "make_thematic_map":
            if result.get("output_png"):
                self.session.current_output = result.get("output_png")

        if tool == "update_preferences":
            self.preferences.update(result.get("updated_preferences", {}))
        if tool == "set_map_style":
            self.session.map_style.update(result.get("map_style", {}))

    def set_plan(self, plan: List[str]) -> None:
        self.session.active_plan = plan
        self.save()

    def mark_completed(self, tool: str) -> None:
        self.session.completed_steps.append(tool)
        self.session.completed_steps = self.session.completed_steps[-30:]
        self.save()

    def task_context(self) -> Dict[str, Any]:
        return {
            "session": self.session.to_prompt_context(),
            "preferences": self.preferences,
        }

    def write_run_log(self, agent_result: Dict[str, Any]) -> str:
        run_path = RUNS_DIR / f"{self.session.task_id}.json"
        run_path.write_text(json.dumps(agent_result, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(run_path)
