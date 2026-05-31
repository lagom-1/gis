"""
导出工具：格式转换、报告生成
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import config as app_config
from tools.base import BaseTool, tool


def _out_dir(runtime=None) -> Path:
    if runtime:
        return runtime.session_dir
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool(
    name="export_result",
    description="把最近结果图导出为 png/jpg/pdf/tif。",
    parameters={
        "format": "png/jpg/pdf/tif",
        "input_path": "可选，输入路径",
        "dpi": "分辨率，默认 300",
    },
    category="export",
)
class ExportResultTool(BaseTool):
    def execute(self, format="png", input_path=None, dpi=300) -> Dict[str, Any]:
        input_path = input_path or self.runtime.last_output
        if not input_path:
            return {"success": False, "message": "没有可导出的结果图"}
        from gis.export import export_image
        stem = Path(input_path).stem
        output_path = str(_out_dir(self.runtime) / f"{stem}_export.{format}")
        result = export_image(
            input_path=input_path, output_path=output_path,
            format=format, dpi=int(dpi),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_path")
        return result


@tool(
    name="generate_report",
    description="生成带文字解读的图文实验报告（HTML格式）。",
    parameters={
        "title": "报告标题",
        "subtitle": "副标题",
        "conclusion": "总结文字",
        "format": "html或pdf",
        "images": "可选，指定要包含的图片路径列表",
        "report_items": "可选，报告项列表 [{section_title, image_path, image_caption, stats}]",
    },
    category="export",
)
class GenerateReportTool(BaseTool):
    def execute(self, title="GIS 实验报告", subtitle="", conclusion="",
                format="html", images=None, report_items=None) -> Dict[str, Any]:
        from gis.report import generate_html_report, try_convert_pdf

        dataset_name = Path(self.runtime.current_dataset or "unknown").stem
        items = list(report_items or [])

        if not items and images:
            for img in images:
                if isinstance(img, str):
                    items.append({
                        "section_title": "",
                        "image_path": img,
                        "image_caption": Path(img).stem,
                    })

        if not items:
            # 智能兜底：扫描会话目录找 TIF，隐式调用统计
            import glob as _glob
            session_tifs = sorted(
                _glob.glob(str(self.runtime.session_dir / "*.tif")),
                key=os.path.getmtime, reverse=True
            )
            tif = self.runtime.current_tif()
            if not tif and session_tifs:
                tif = session_tifs[0]
            if tif:
                try:
                    from gis.statistics import analyze_raster
                    stats = analyze_raster(tif)
                    if stats.get("success") and stats.get("histogram_png"):
                        items.append({
                            "section_title": "数据统计分析",
                            "item_type": "statistics",
                            "image_path": stats["histogram_png"],
                            "image_caption": f"{dataset_name} 像元值分布直方图",
                            "stats": stats.get("statistics", {}),
                        })
                except Exception:
                    pass
            # 收集已有 PNG 文件
            if self.runtime.last_output and self.runtime.last_output.endswith(('.png', '.jpg')):
                items.append({
                    "section_title": "专题图", "item_type": "map",
                    "image_path": self.runtime.last_output, "image_caption": dataset_name,
                })
            for f in self.runtime.output_files:
                if f.get("name", "").endswith(('.png', '.jpg')) and not any(
                    i.get("image_path") == f.get("path") for i in items
                ):
                    items.append({
                        "section_title": "", "item_type": "map",
                        "image_path": f["path"], "image_caption": f["name"],
                    })

        if not items:
            return {"success": False, "message": "没有可用的分析结果来生成报告。"}

        output_path = str(_out_dir(self.runtime) / f"{dataset_name}_experiment_report.html")
        result = generate_html_report(
            report_items=items, output_path=output_path,
            title=title, subtitle=subtitle,
            dataset_name=dataset_name, conclusion=conclusion,
        )
        if result.get("success") and format == "pdf":
            pdf = try_convert_pdf(output_path)
            if pdf.get("success"):
                result["pdf_path"] = pdf["pdf_path"]
        if result.get("success"):
            self.runtime.last_output = output_path
        return result
