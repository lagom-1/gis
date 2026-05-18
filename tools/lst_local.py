"""
本地 LST 反演工具（SCA 算法）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import config as app_config
from tools.base import BaseTool, tool


def _out_dir() -> Path:
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool(
    name="run_lst",
    description="对当前多波段影像执行地表温度反演（SCA算法），生成 LST 栅格和预览图。",
    parameters={"input_tif": "可选，输入栅格路径"},
    category="analysis",
)
class RunLSTTool(BaseTool):
    def execute(self, input_tif=None) -> Dict[str, Any]:
        tif = input_tif or self.runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用输入影像"}
        from gis.sca_runner import run_sca
        stem = Path(tif).stem
        output_tif = str(_out_dir() / f"{stem}_lst.tif")
        output_png = str(_out_dir() / f"{stem}_lst.png")
        result = run_sca(input_tif=tif, output_tif=output_tif, output_png=output_png)
        if result.get("success"):
            self.runtime.current_dataset = output_tif
            self.runtime.last_tif_output = output_tif
            self.runtime.last_output = output_png
        return result
