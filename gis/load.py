"""安全的数据下载脚本示例。不要在代码里硬编码 AK/SK。"""

import os

import openxlab
from openxlab.dataset import get


def download_second_dataset(target_path: str = './second_dataset'):
    ak = os.getenv('OPENXLAB_AK')
    sk = os.getenv('OPENXLAB_SK')
    if not ak or not sk:
        raise RuntimeError('缺少 OPENXLAB_AK / OPENXLAB_SK，请使用环境变量配置。')
    openxlab.login(ak=ak, sk=sk)
    get(dataset_repo='OpenDataLab/SECOND', target_path=target_path)
