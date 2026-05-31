"""安全的数据下载脚本示例。不要在代码里硬编码 AK/SK。"""

import os

import openxlab
from openxlab.dataset import get


def download_second_dataset(target_path: str = './second_dataset') -> dict:
    ak = os.getenv('OPENXLAB_AK')
    sk = os.getenv('OPENXLAB_SK')
    if not ak or not sk:
        return {"success": False, "message": "缺少 OPENXLAB_AK / OPENXLAB_SK，请使用环境变量配置。"}
    try:
        openxlab.login(ak=ak, sk=sk)
        get(dataset_repo='OpenDataLab/SECOND', target_path=target_path)
        return {"success": True, "message": f"SECOND 数据集已下载到: {target_path}", "output_dir": target_path}
    except Exception as e:
        return {"success": False, "message": f"下载 SECOND 数据集失败: {e}"}
