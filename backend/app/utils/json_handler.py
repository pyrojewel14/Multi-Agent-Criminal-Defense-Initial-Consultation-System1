import os
import json
from typing import List
from langchain_core.documents import Document
from app.utils.logger import get_logger

_logger = get_logger("JSONHandler")


async def json_loader(file_path: str) -> List[Document]:
    """
    加载 JSON 文件内容。

    Args:
        file_path: JSON 文件路径。

    Returns:
        JSON 文件内容列表。
    """
    try:
        abs_file_path = get_abstract_path(file_path) if not os.path.isabs(file_path) else file_path
        
        with open(abs_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            content = json.dumps(data, ensure_ascii=False, indent=2)
        elif isinstance(data, dict):
            content = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            content = str(data)
        
        metadata = {
            'source_type': 'legal_json',
            'source': abs_file_path
        }
        
        return [Document(page_content=content, metadata=metadata)]
    except Exception as e:
        _logger.error("JSON 文件加载失败: %s, %s", file_path, e)
        return []


def json_loader_sync(file_path: str) -> List[Document]:
    """
    同步加载 JSON 文件内容（用于多线程场景）。

    Args:
        file_path: JSON 文件路径。

    Returns:
        JSON 文件内容列表。
    """
    try:
        abs_file_path = get_abstract_path(file_path) if not os.path.isabs(file_path) else file_path
        
        with open(abs_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            content = json.dumps(data, ensure_ascii=False, indent=2)
        elif isinstance(data, dict):
            content = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            content = str(data)
        
        metadata = {
            'source_type': 'legal_json',
            'source': abs_file_path
        }
        
        return [Document(page_content=content, metadata=metadata)]
    except Exception as e:
        _logger.error("JSON 文件加载失败（同步）: %s, %s", file_path, e)
        return []
