from typing import List, Dict, Any
import torch
import os
from dotenv import load_dotenv
from sentence_transformers import CrossEncoder
from modelscope import snapshot_download
from tqdm import tqdm
from app.utils.logger import get_logger

load_dotenv()


_logger = get_logger("Reorder")


def find_model_path(base_path: str) -> str:
    """在指定目录下递归查找包含 config.json 的模型文件夹。

    Args:
        base_path: 搜索的起始路径。

    Returns:
        包含 config.json 的目录路径。
    """
    if os.path.exists(os.path.join(base_path, 'config.json')):
        return base_path

    for root, dirs, files in os.walk(base_path):
        if 'config.json' in files:
            _logger.info("模型路径: %s", root)
            return root

    _logger.info("模型路径: %s", base_path)
    return base_path


def check_and_download_reranker_model() -> None:
    """检查重排序模型是否存在，如不存在则从魔搭社区下载。"""
    local_model_path = os.getenv("RERANKER_MODEL_PATH", "./data/models/Qwen3-Reranker-0.6B")
    modelscope_model_name = "Qwen/Qwen3-Reranker-0.6B"

    try:
        if os.path.exists(local_model_path) and os.path.isdir(local_model_path):
            _logger.info("检测到本地重排序模型: %s", local_model_path)
        else:
            _logger.warning("本地模型未找到: %s", local_model_path)
            _logger.info("开始从魔搭社区下载模型: %s", modelscope_model_name)

            os.makedirs(local_model_path, exist_ok=True)

            with tqdm(total=100, desc='下载模型', leave=True, bar_format='{l_bar}{bar}| {n_fmt}%') as pbar:
                pbar.update(10)
                snapshot_download(
                    model_id=modelscope_model_name,
                    cache_dir=local_model_path,
                    revision='master'
                )
                pbar.update(90)

            _logger.info("模型下载完成，保存路径: %s", local_model_path)

    except Exception as e:
        _logger.error("模型检查失败: %s", str(e))
        raise RuntimeError(f"重排序模型检查失败: {str(e)}")


class ReorderService:
    """文档重排序服务"""

    def __init__(self):
        self.local_model_path = os.getenv("RERANKER_MODEL_PATH", "./data/models/Qwen3-Reranker-0.6B")
        self.modelscope_model_name = "Qwen/Qwen3-Reranker-0.6B"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = None
        self._model_unavailable = False

    async def _ensure_model(self) -> bool:
        """确保模型文件存在，不存在则尝试下载。

        Returns:
            模型是否可用。
        """
        if self._model_unavailable:
            return False

        actual_path = find_model_path(self.local_model_path)
        if os.path.exists(os.path.join(actual_path, 'config.json')):
            return True

        _logger.info("重排序模型不存在，尝试从 ModelScope 下载: %s", self.modelscope_model_name)
        try:
            os.makedirs(self.local_model_path, exist_ok=True)
            snapshot_download(
                model_id=self.modelscope_model_name,
                cache_dir=self.local_model_path,
                revision='master'
            )
            _logger.info("重排序模型下载完成")
            return True
        except Exception as e:
            _logger.warning("重排序模型下载失败，将跳过重排序: %s", e)
            self._model_unavailable = True
            return False

    async def _get_model(self):
        """懒加载模型实例。"""
        if self._model is not None:
            return self._model

        if not await self._ensure_model():
            return None

        actual_model_path = find_model_path(self.local_model_path)
        _logger.info("加载重排序模型: %s", actual_model_path)
        try:
            self._model = CrossEncoder(
                actual_model_path,
                max_length=512,
                device=self.device,
            )
            self._model.eval()
            _logger.info("模型加载成功，使用设备: %s", self.device)
        except Exception as e:
            _logger.warning("重排序模型加载失败，将跳过重排序: %s", e)
            self._model_unavailable = True
            return None

        return self._model

    @property
    async def model(self):
        """获取模型实例（懒加载）。

        Returns:
            CrossEncoder 模型实例，不可用时返回 None。
        """
        return await self._get_model()

    async def reorder_documents(
        self, query: str, documents: List[str], thinking_callback=None
    ) -> Dict[str, Any]:
        """对文档进行重排序。

        Args:
            query: 查询语句。
            documents: 文档列表。
            thinking_callback: 思考过程回调函数。

        Returns:
            包含重排序结果的字典，格式为：
            {"success": bool, "documents": List[Dict], "error": str}
        """
        try:
            if not documents:
                return {
                    "success": True,
                    "documents": [],
                    "error": ""
                }

            if thinking_callback:
                await thinking_callback({
                    "type": "thinking",
                    "stage": "reorder",
                    "content": f"正在计算 {len(documents)} 个文档的相关性分数..."
                })

            pairs = [(query, doc) for doc in documents]

            model = await self.model
            if model is None:
                return {
                    "success": False,
                    "documents": [],
                    "error": "重排序模型不可用，跳过重排序"
                }

            with torch.no_grad():
                scores = model.predict(pairs, batch_size=1)

            scored_documents = []
            for doc, score in zip(documents, scores):
                scored_documents.append({
                    "document": doc,
                    "similarity": float(score)
                })
                _logger.debug("文档相似度分数: %.4f", float(score))

            if thinking_callback:
                score_details = []
                for i, (doc, score) in enumerate(zip(documents, scores), 1):
                    score_details.append({
                        "index": i,
                        "score": round(float(score), 4),
                        "preview": doc[:100] + "..." if len(doc) > 100 else doc
                    })
                await thinking_callback({
                    "type": "thinking",
                    "stage": "reorder",
                    "content": f"已计算完成 {len(documents)} 个文档的相关性分数，按分数降序排序",
                    "details": {
                        "scores": score_details
                    }
                })

            sorted_docs = sorted(scored_documents, key=lambda x: x["similarity"], reverse=True)
            _logger.info("文档重排序成功，返回 %d 个文档", len(sorted_docs))

            return {
                "success": True,
                "documents": sorted_docs,
                "error": ""
            }
        except Exception as e:
            error_msg = str(e)
            _logger.error("重排序失败: %s", error_msg)
            return {
                "success": False,
                "documents": [],
                "error": error_msg
            }

    @staticmethod
    async def format_reorder_result(sorted_docs: List[Dict]) -> str:
        """格式化重排序结果。

        Args:
            sorted_docs: 重排序后的文档列表。

        Returns:
            格式化后的字符串。
        """
        formatted_result = "重排序后的文档列表：\n"
        for i, doc in enumerate(sorted_docs, 1):
            formatted_result += f"{i}. 相似度: {doc.get('similarity', 0):.4f}\n"
            formatted_result += f"   内容: {doc.get('document', '')}\n\n"
        return formatted_result


reorder_service = ReorderService()
