"""
文件发现模块 - 智能搜索本地栅格文件
支持：模糊搜索、按扩展名过滤、智能排序
"""

import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import RASTER_EXTS, default_search_roots


def find_local_files(
    query: str,
    roots: Optional[List[str]] = None,
    max_results: int = 20,
    extensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    搜索本地文件

    Args:
        query: 文件名关键词（支持空格分词匹配）
        roots: 搜索根目录列表，None 则使用默认目录
        max_results: 最大返回数
        extensions: 限定扩展名列表
    """
    query = (query or "").strip().lower()
    roots = roots or default_search_roots()
    ext_filter = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (extensions or [])}

    results: List[Dict[str, Any]] = []
    query_tokens = [t for t in query.replace("_", " ").replace("-", " ").split() if t]

    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext_filter and ext not in ext_filter:
                    continue
                hay = name.lower()
                path = os.path.join(dirpath, name)
                matched = False
                if not query:
                    matched = True
                elif query in hay or fnmatch.fnmatch(hay, f"*{query}*"):
                    matched = True
                elif query_tokens and all(tok in hay for tok in query_tokens):
                    matched = True
                if not matched:
                    continue
                try:
                    st = os.stat(path)
                    size_bytes = st.st_size
                    mtime = st.st_mtime
                except OSError:
                    size_bytes = 0
                    mtime = 0
                score = 0
                if query and hay == query:
                    score += 100
                score += sum(10 for tok in query_tokens if tok in hay)
                if ext in RASTER_EXTS:
                    score += 5
                results.append({
                    "name": name,
                    "path": path,
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "mtime": mtime,
                    "score": score,
                })
                if len(results) > max_results * 8:
                    break
            if len(results) > max_results * 8:
                break
        if len(results) > max_results * 8:
            break

    results.sort(key=lambda x: (-x["score"], -x["mtime"], x["name"]))
    results = results[:max_results]
    raster_hits = [r for r in results if r["extension"] in RASTER_EXTS]

    return {
        "success": bool(results),
        "message": f"找到 {len(results)} 个候选文件" if results else f"未找到匹配文件: {query}",
        "files": results,
        "raster_candidates": raster_hits,
        "selected_path": raster_hits[0]["path"] if raster_hits else (results[0]["path"] if results else None),
        "roots": roots,
    }