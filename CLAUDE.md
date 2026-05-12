# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AI-driven GIS (Geographic Information System) platform that combines a raster processing library with an LLM-powered intelligent agent. Users interact in natural language (Chinese), and the agent autonomously plans and executes GIS workflows including remote sensing data download, land surface temperature (LST) inversion, classification, cartographic mapping, and 3D visualization.

## Architecture

### Three-layer design

1. **`gis/` package** — Pure-function GIS processing modules. Each module reads a GeoTIFF, processes it, and returns a standardized result dict: `{"success": bool, "message": str, ...}`. Modules do not share state.

2. **`agent/` package** — LLM-driven agent engine. `GISAgent` (in `agent/core.py`) is the main entry point. It uses `LLMClient` (Qwen/Tongyi via LangChain) to decide which tool to call next. LLM is the sole decision-making path; if LLM is unavailable, the agent raises an error.

3. **`config.py`** — Central configuration: paths, default map styles, raster extensions, GEE settings, user preferences.

### Agent workflow

```
User input → LLM decision (agent/prompts.py: DECISION_SYSTEM_PROMPT)
  → Tool execution (agent/tool.py: register_tools → ToolRegistry)
  → State update (agent/memory.py: MemoryStore)
  → Loop or final answer
```

- `agent/tool_registry.py` — `ToolRegistry` maps tool names to `ToolSpec` + handler functions
- `agent/tool.py` — `GISRuntime` holds mutable session state (current_dataset, map_style, etc.); `register_tools()` wires all 25+ tools
- `agent/memory.py` — `MemoryStore` persists session state and user preferences to `workspace/memory.json` and `workspace/preferences.json`
- `agent/llm_client.py` — `LLMClient` wraps ChatTongyi with JSON parsing, retry, and error recovery
- `agent/prompts.py` — The decision prompt contains strict workflow rules (GEE pipeline, admin region resolution, timelapse, anti-loop)

### Key GIS modules

| Module | Purpose |
|--------|---------|
| `gis/sca_runner.py` | Single-channel algorithm (SCA) for LST inversion from Landsat thermal bands |
| `gis/inspect.py` | Raster metadata inspection + product type inference |
| `gis/file_discovery.py` | Smart local file search with fuzzy matching |
| `gis/cartographic_map.py` | Publication-quality thematic maps with legend, scalebar, north arrow |
| `gis/classify.py` | Raster classification (natural breaks, equal interval, quantile) |
| `gis/statistics.py` | Single-band statistics + histogram |
| `gis/enhance.py` | Image enhancement (Gaussian, median, CLAHE, sharpening) |
| `gis/threshold.py` | Threshold-based pixel highlighting |
| `gis/compare.py` | Side-by-side or difference comparison views |
| `gis/profile.py` | Transect profile analysis |
| `gis/view3d.py` | 3D surface/wireframe/contour rendering |
| `gis/transform.py` | Flip/rotate raster |
| `gis/export.py` | Image format conversion (PNG/JPG/PDF/TIFF) |
| `gis/report.py` | HTML experiment report generation |
| `gis/web_map.py` | Interactive Leaflet web maps |
| `gis/admin_region.py` | Chinese administrative boundary resolution from local GeoJSON |
| `gis/gee_tools.py` | Google Earth Engine initialization and Landsat data download |
| `gis/gee_timelapse.py` | Multi-year LST time series: GIF, split-panel, trend chart |

## Running the Agent

The main entry point is `GISAgent.run()`:

```python
from agent.core import GISAgent
agent = GISAgent(max_steps=25)
result = agent.run("找到Beijing的tif，做温度反演并制图")
print(result["final_answer"])
```

## Environment Variables

- `DASHSCOPE_API_KEY` — Required for LLM mode (Qwen/Tongyi). Without it, agent initialization will fail.
- `QWEN_MODEL` — Model name (default: `qwen-plus`)
- `QWEN_TEMPERATURE` — LLM temperature (default: `0.1`)
- `OPENXLAB_AK` / `OPENXLAB_SK` — For OpenXLab dataset downloads
- `GEE_DRIVE_FOLDER` — Google Drive export folder for GEE
- `GDRIVE_SYNC_DIR` — Local Google Drive sync directory path

## Key Design Patterns

- All GIS functions return a dict with at least `success` (bool) and `message` (str). On success, they also include output paths (`output_png`, `output_tif`).
- `GISRuntime` is the single source of truth for session state. Tools read/write `runtime.current_dataset`, `runtime.last_output`, `runtime.map_style`.
- The agent has cycle detection: if `set_map_style` or `make_thematic_map` is called twice in one turn, it forces a `final` response.
- Chinese administrative region names (e.g., "温江区", "旺苍县") are resolved to GeoJSON boundaries via local files before GEE operations.
- GEE workflow: `resolve_admin_region` → `gee_download_landsat_sca` → `run_lst` → `make_thematic_map`. This order is enforced by the decision prompt and `_validate_decision()`.

## Supported Raster Formats

`.tif`, `.tiff`, `.img`, `.jp2`, `.vrt`, `.asc`, `.hdf`, `.nc` (defined in `config.RASTER_EXTS`)

## Workspace Structure

- `workspace/runs/` — JSON logs of each agent execution
- `workspace/outputs/` — Generated PNG/TIF/HTML outputs
- `workspace/memory.json` — Session memory persistence
- `workspace/preferences.json` — User preference persistence
