"""
报告生成模块 - 将分析结果生成带文字解读的图文实验报告
支持 HTML 和 PDF 两种格式
"""

from __future__ import annotations

import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _img_to_base64(img_path: str) -> str:
    """将图片转为 base64 data URI，便于嵌入 HTML"""
    if not img_path or not os.path.exists(img_path):
        return ""
    ext = Path(img_path).suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}.get(ext, "image/png")
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _interpret_statistics(stats: Dict[str, Any], dataset_name: str = "") -> str:
    """根据统计数据自动生成文字解读"""
    if not stats:
        return ""

    mean = stats.get("mean", 0)
    std = stats.get("std", 0)
    min_val = stats.get("min", 0)
    max_val = stats.get("max", 0)
    median = stats.get("median", 0)
    count = stats.get("count", 0)
    p25 = stats.get("p25", 0)
    p75 = stats.get("p75", 0)
    p95 = stats.get("p95", 0)

    cv = (std / mean * 100) if mean != 0 else 0
    range_val = max_val - min_val
    iqr = p75 - p25

    # 偏度判断
    skew_desc = ""
    if abs(mean - median) < std * 0.1:
        skew_desc = "数据分布接近正态"
    elif mean > median:
        skew_desc = "数据呈右偏分布，存在高值异常拉高均值"
    else:
        skew_desc = "数据呈左偏分布，存在低值异常拉低均值"

    # 离散程度
    if cv < 10:
        cv_desc = "变异较小，空间分布较为均匀"
    elif cv < 30:
        cv_desc = "变异中等，存在一定的空间异质性"
    else:
        cv_desc = "变异较大，空间异质性显著"

    # 极端值
    extreme_desc = ""
    if p95 > mean + 2 * std:
        extreme_desc = "前5%的高值区域显著高于平均水平，可能存在热点区域。"

    parts = [
        f"**数据概况**：有效像元 {count:,} 个。",
        f"**数值范围**：最小值 {min_val:.4f}，最大值 {max_val:.4f}，极差 {range_val:.4f}。",
        f"**集中趋势**：均值 {mean:.4f}，中位数 {median:.4f}。{skew_desc}。",
        f"**离散程度**：标准差 {std:.4f}，变异系数 {cv:.1f}%，{cv_desc}。",
        f"**四分位距**：IQR = {iqr:.4f}（Q1 = {p25:.4f}，Q3 = {p75:.4f}）。",
    ]
    if extreme_desc:
        parts.append(f"**极端值分析**：P95 = {p95:.4f}，{extreme_desc}")

    return "\n\n".join(parts)


def _interpret_classification(class_stats: List[Dict[str, Any]], method_desc: str = "") -> str:
    """自动生成分类结果的文字解读"""
    if not class_stats:
        return ""

    parts = [f"本次分类采用**{method_desc}**方法，共分为 {len(class_stats)} 个等级。各类别面积占比如下：\n"]

    for cs in class_stats:
        label = cs.get("label", f"类别{cs.get('class', '')}")
        pct = cs.get("pct", 0)
        count = cs.get("count", 0)
        bar = "█" * int(pct / 2)
        parts.append(f"- {label}：占比 {pct}%（{count:,} 像元）{bar}")

    # 找主导类别
    if class_stats:
        dominant = max(class_stats, key=lambda x: x.get("pct", 0))
        minor = min(class_stats, key=lambda x: x.get("pct", 0))
        parts.append(f"\n**主导类别**：{dominant['label']}，覆盖 {dominant['pct']}% 的区域。")
        if minor["pct"] < 5:
            parts.append(f"**稀有类别**：{minor['label']}，仅占 {minor['pct']}%，属于少量异常或边缘区域。")

    return "\n".join(parts)


def _interpret_threshold(stats_before: Dict, stats_after: Dict, operator: str, value: float) -> str:
    """阈值分析解读"""
    count = stats_after.get("count", 0) if stats_after else 0
    total = stats_before.get("count", 1) if stats_before else 1
    pct = count / total * 100 if total > 0 else 0

    op_text = {"大于": ">", "小于": "<", "介于": "between", "外于": "outside"}.get(operator, operator)

    return (
        f"以阈值 {op_text} {value} 进行筛选，"
        f"符合条件的像元共 {count:,} 个，占总有效像元的 {pct:.1f}%。"
        + (" 高亮区域面积较大，需关注其空间分布特征。" if pct > 30
           else " 高亮区域面积较小，可能为局部异常或热点。" if pct < 5
           else " 高亮区域占比适中。")
    )


def generate_html_report(
    report_items: List[Dict[str, Any]],
    output_path: str,
    title: str = "GIS 实验报告",
    subtitle: str = "",
    dataset_name: str = "",
    conclusion: str = "",
) -> Dict[str, Any]:
    """
    生成图文实验报告（HTML 格式）

    Args:
        report_items: 报告内容列表，每项包含:
            - section_title: 章节标题
            - image_path: 图片路径（可选）
            - image_caption: 图片说明（可选）
            - text: 文字内容（支持 Markdown 简单语法）
            - stats: 统计数据字典（可选，用于自动生成解读）
            - item_type: "statistics" / "classification" / "threshold" / "map" / "custom"
            - extra_data: 额外数据（可选）
        output_path: 输出 HTML 文件路径
        title: 报告标题
        subtitle: 副标题
        dataset_name: 数据集名称
        conclusion: 总结文字

    Returns:
        {"success": True, "output_path": "...", "message": "..."}
    """
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sections_html = []
        for i, item in enumerate(report_items, 1):
            section_title = item.get("section_title", f"第{i}部分")
            image_path = item.get("image_path", "")
            image_caption = item.get("image_caption", "")
            text = item.get("text", "")
            stats = item.get("stats", {})
            item_type = item.get("item_type", "custom")
            extra_data = item.get("extra_data", {})

            # 自动生成文字解读（如果 text 为空但有 stats）
            if not text and item_type == "statistics" and stats:
                text = _interpret_statistics(stats, dataset_name)
            elif not text and item_type == "classification":
                class_stats = extra_data.get("class_stats", [])
                method_desc = extra_data.get("method", "")
                text = _interpret_classification(class_stats, method_desc)
            elif not text and item_type == "threshold":
                text = _interpret_threshold(
                    extra_data.get("stats_before", {}),
                    stats,
                    extra_data.get("operator", ">"),
                    extra_data.get("value", 0),
                )

            # 简单 Markdown → HTML
            text_html = _md_to_html(text) if text else ""

            # 图片
            img_html = ""
            if image_path and os.path.exists(image_path):
                b64 = _img_to_base64(image_path)
                caption_html = f'<p class="caption">{image_caption}</p>' if image_caption else ""
                img_html = f'''
                <div class="figure">
                    <img src="{b64}" alt="{image_caption}" />
                    {caption_html}
                </div>'''

            sections_html.append(f'''
            <div class="section">
                <h2>{i}. {section_title}</h2>
                {text_html}
                {img_html}
            </div>''')

        # 结论
        conclusion_html = ""
        if conclusion:
            conclusion_html = f'''
            <div class="section conclusion">
                <h2>结论与讨论</h2>
                {_md_to_html(conclusion)}
            </div>'''

        # 组装完整 HTML
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
    @page {{
        size: A4;
        margin: 2cm;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "SimHei", sans-serif;
        line-height: 1.8;
        color: #2c3e50;
        max-width: 900px;
        margin: 0 auto;
        padding: 40px 30px;
        background: #fff;
    }}
    .header {{
        text-align: center;
        border-bottom: 3px solid #2c3e50;
        padding-bottom: 25px;
        margin-bottom: 35px;
    }}
    .header h1 {{
        font-size: 28px;
        color: #1a1a2e;
        margin-bottom: 8px;
        letter-spacing: 2px;
    }}
    .header .subtitle {{
        font-size: 16px;
        color: #7f8c8d;
        margin-bottom: 15px;
    }}
    .header .meta {{
        font-size: 13px;
        color: #95a5a6;
    }}
    .section {{
        margin-bottom: 30px;
        page-break-inside: avoid;
    }}
    .section h2 {{
        font-size: 20px;
        color: #2c3e50;
        border-left: 4px solid #3498db;
        padding-left: 12px;
        margin-bottom: 15px;
    }}
    .section p, .section ul, .section ol {{
        margin-bottom: 12px;
        text-align: justify;
    }}
    .section ul, .section ol {{
        padding-left: 25px;
    }}
    .section li {{
        margin-bottom: 5px;
    }}
    .figure {{
        text-align: center;
        margin: 20px 0;
        page-break-inside: avoid;
    }}
    .figure img {{
        max-width: 100%;
        height: auto;
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}
    .figure .caption {{
        font-size: 13px;
        color: #7f8c8d;
        margin-top: 8px;
        font-style: italic;
    }}
    .conclusion {{
        background: #f8f9fa;
        padding: 20px 25px;
        border-radius: 6px;
        border-left: 4px solid #e74c3c;
    }}
    .conclusion h2 {{
        border-left-color: #e74c3c;
    }}
    .footer {{
        text-align: center;
        font-size: 12px;
        color: #bdc3c7;
        margin-top: 40px;
        padding-top: 15px;
        border-top: 1px solid #ecf0f1;
    }}
    strong {{ color: #2c3e50; }}
    em {{ color: #7f8c8d; }}
</style>
</head>
<body>

<div class="header">
    <h1>{title}</h1>
    <div class="subtitle">{subtitle}</div>
    <div class="meta">
        数据集：{dataset_name or "未指定"} &nbsp;|&nbsp; 生成时间：{now}
    </div>
</div>

{''.join(sections_html)}

{conclusion_html}

<div class="footer">
    本报告由 GIS 智能分析系统自动生成
</div>

</body>
</html>'''

        # 写入文件
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        return {
            "success": True,
            "message": f"实验报告已生成: {output_path}",
            "output_path": output_path,
            "format": "html",
            "sections_count": len(report_items),
        }

    except Exception as e:
        return {"success": False, "message": f"报告生成失败: {e}"}


def try_convert_pdf(html_path: str) -> Dict[str, Any]:
    """尝试将 HTML 转为 PDF（需要 weasyprint）"""
    try:
        from weasyprint import HTML as WeasyHTML
        pdf_path = html_path.rsplit(".", 1)[0] + ".pdf"
        WeasyHTML(filename=html_path).write_pdf(pdf_path)
        return {"success": True, "pdf_path": pdf_path, "message": f"PDF 已生成: {pdf_path}"}
    except ImportError:
        return {"success": False, "message": "weasyprint 未安装，跳过 PDF 生成（HTML 报告已就绪）"}
    except Exception as e:
        return {"success": False, "message": f"PDF 转换失败: {e}"}


def _md_to_html(text: str) -> str:
    """简单 Markdown → HTML 转换（加粗、斜体、列表、段落）"""
    if not text:
        return ""

    lines = text.strip().split("\n")
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        # 列表项
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = _inline_md(content)
            html_parts.append(f"  <li>{content}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<p>{_inline_md(stripped)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _inline_md(text: str) -> str:
    """行内 Markdown：**粗体**、*斜体*"""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text