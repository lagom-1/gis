"""
文件发现模块 - 智能搜索本地栅格文件
支持：模糊搜索、按扩展名过滤、智能排序
"""

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import RASTER_EXTS, default_search_roots

# 搜索限制
MAX_WALK_DEPTH = 6  # 最大目录深度
MIN_TOKEN_LENGTH = 2  # 最小 token 长度


def find_local_files(
    query: str,
    roots: Optional[List[str]] = None,
    max_results: int = 20,
    extensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    搜索本地文件。优先搜索 workspace/outputs/ 目录，确保项目产出文件快速命中。

    Args:
        query: 文件名关键词（支持空格分词匹配）
        roots: 搜索根目录列表，None 则使用默认目录
        max_results: 最大返回数
        extensions: 限定扩展名列表
    """
    query = (query or "").strip().lower()
    ext_filter = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (extensions or [])}

    # 过滤掉过短的 token（至少 1 个字符）
    query_tokens = [
        t for t in query.replace("_", " ").replace("-", " ").split()
        if t and len(t) >= 1
    ]

    results: List[Dict[str, Any]] = []

    def _match(name: str) -> bool:
        """检查文件名是否匹配查询（支持无分隔符模糊匹配）"""
        hay = name.lower()
        if not query:
            return True
        if query in hay or fnmatch.fnmatch(hay, f"*{query}*"):
            return True
        if query_tokens and all(tok in hay for tok in query_tokens):
            return True
        # 归一化匹配：去掉分隔符、空格和中文字符后再比较
        hay_norm = re.sub(r'[_\- ]', '', hay)
        query_norm = re.sub(r'[_\- 年月日]', '', query)
        if query_norm and query_norm in hay_norm:
            return True
        # 零填充匹配: "1月" → "01", "2月" → "02"
        zp_query = query
        for m in re.finditer(r'(\d{1,2})\s*月', query):
            zp_query = zp_query.replace(m.group(0), m.group(1).zfill(2))
        zp_query_norm = re.sub(r'[_\- 年月日]', '', zp_query)
        if zp_query_norm and zp_query_norm in hay_norm:
            return True
        # 匹配: 提取区域名（去除数字和年月后）在文件名中
        region_part = re.sub(r'[\d年月日]', '', query).replace('_', '').replace(' ', '')
        if len(region_part) >= 2 and region_part in hay.replace('_', '').replace(' ', ''):
            return True
        return False

    def _scan_dir(directory: str, depth: int = 0, max_depth: int = 4) -> bool:
        """递归扫描目录，返回是否因找到足够结果而中止"""
        if depth > max_depth:
            return False
        try:
            entries = os.scandir(directory)
        except OSError:
            return False

        dirs_to_scan = []
        for entry in entries:
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext_filter and ext not in ext_filter:
                    continue
                if not _match(entry.name):
                    continue
                try:
                    st = entry.stat()
                    size_bytes = st.st_size
                    mtime = st.st_mtime
                except OSError:
                    size_bytes = 0
                    mtime = 0
                score = 0
                if query and entry.name.lower() == query:
                    score += 100
                score += sum(10 for tok in query_tokens if tok in entry.name.lower())
                if ext in RASTER_EXTS:
                    score += 5
                score -= depth * 2
                results.append({
                    "name": entry.name,
                    "path": entry.path,
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "mtime": mtime,
                    "score": score,
                })
            elif entry.is_dir() and not entry.name.startswith('.'):
                skip_dirs = {
                    'node_modules', '__pycache__', '.git', '.venv',
                    'venv', 'env', '.idea', '.vscode', '.next',
                }
                if entry.name not in skip_dirs:
                    dirs_to_scan.append(entry.path)

            if len(results) >= max_results:
                return True

        for d in dirs_to_scan:
            if _scan_dir(d, depth + 1, max_depth):
                return True
        return False

    # ── 第一优先级：workspace/outputs/ 目录，递归扫描所有子目录 ──
    from config import OUTPUTS_DIR
    outputs_dir = str(OUTPUTS_DIR)
    if os.path.isdir(outputs_dir):
        _scan_dir(outputs_dir, depth=0, max_depth=8)  # outputs 内深度放宽

    # 如果 outputs 里没找到足够结果，扫描 workspace/ 根目录
    if len(results) < max_results:
        from config import WORKSPACE_DIR
        ws_dir = str(WORKSPACE_DIR)
        if os.path.isdir(ws_dir):
            _scan_dir(ws_dir, depth=0, max_depth=5)

    # ── 第二优先级：用户指定或默认的搜索根目录 ──
    if len(results) < max_results:
        roots = roots or default_search_roots()
        for root in roots:
            if not os.path.exists(root):
                continue
            root_path = str(Path(root).resolve())
            if root_path in {outputs_dir, str(WORKSPACE_DIR)}:
                continue  # 已搜索过
            # 跳过整个盘符根目录（太慢）
            if root_path in {"C:\\", "D:\\", "E:\\", "G:\\"}:
                continue
            _scan_dir(root_path, depth=0, max_depth=4)
            if len(results) >= max_results:
                break

    results.sort(key=lambda x: (-x["score"], -x["mtime"], x["name"]))
    # 按 path 去重（同一物理文件只保留得分最高的）
    seen_paths = set()
    deduped = []
    for r in results:
        norm_path = os.path.normpath(r["path"])
        if norm_path not in seen_paths:
            seen_paths.add(norm_path)
            deduped.append(r)
    results = deduped[:max_results]
    raster_hits = [r for r in results if r["extension"] in RASTER_EXTS]

    return {
        "success": bool(results),
        "message": f"找到 {len(results)} 个候选文件（优先扫描 workspace/outputs/）" if results else f"在 workspace/outputs/ 及常用目录中未找到匹配文件: {query}",
        "files": results,
        "raster_candidates": raster_hits,
        "selected_path": raster_hits[0]["path"] if raster_hits else (results[0]["path"] if results else None),
        "roots": roots,
    }
