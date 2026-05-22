from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

_logger = get_logger("RAG.Reranker")


@dataclass
class RerankerConfig:
    """重排序模型配置。

    Attributes:
        model_name: 模型名称（ModelScope ID）。
        local_path: 本地模型路径。
        cache_dir: 模型缓存目录。
        max_length: 最大输入长度。
        device: 设备类型（cuda/cpu/auto）。
        positive_token: 正样本标记 token。
        negative_token: 负样本标记 token。
        instruction: 检索指令。
        prefix_template: 输入前缀模板。
        suffix_template: 输入后缀模板。
        input_template: 输入格式化模板。
    """

    model_name: str = "Qwen/Qwen3-Reranker-0.6B"
    local_path: str = "./data/models/Qwen/Qwen3-Reranker-0.6B"
    cache_dir: str = "./data/models"
    max_length: int = 512
    device: str = "auto"
    positive_token: str = "true"
    negative_token: str = "false"
    instruction: Optional[str] = None
    prefix_template: str = "<|im_start|>user\n"
    suffix_template: str = "<|im_end|>\n<|im_start|>assistant\n"
    input_template: str = "<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"

    @classmethod
    def from_env(cls) -> "RerankerConfig":
        """从环境变量加载配置。

        Returns:
            RerankerConfig 实例。
        """
        import os

        return cls(
            model_name=os.getenv("RERANKER_MODEL_NAME", "Qwen/Qwen3-Reranker-0.6B"),
            local_path=os.getenv("RERANKER_MODEL_PATH", "./data/models/Qwen/Qwen3-Reranker-0.6B"),
            cache_dir=os.getenv("MODEL_CACHE_DIR", "./data/models"),
            max_length=int(os.getenv("RERANKER_MAX_LENGTH", "512")),
            instruction=os.getenv("RERANKER_INSTRUCTION", None),
        )


class BaseReranker(ABC):
    """重排序基类，定义通用接口和流程。"""

    def __init__(self, config: RerankerConfig):
        """初始化重排序器。

        Args:
            config: 重排序模型配置。
        """
        self.config = config
        self._model = None
        self._tokenizer = None

    @abstractmethod
    async def _load_model(self):
        """加载模型和分词器，子类实现。"""

    @abstractmethod
    async def _format_pairs(self, query: str, documents: List[str]) -> List[str]:
        """格式化查询-文档对，子类实现。

        Args:
            query: 查询语句。
            documents: 文档列表。

        Returns:
            格式化后的配对列表。
        """

    @abstractmethod
    async def _compute_scores(self, pairs: List[str]) -> List[float]:
        """计算相关性分数，子类实现。

        Args:
            pairs: 格式化后的配对列表。

        Returns:
            分数列表。
        """

    async def rerank(self, query: str, documents: List[str], thinking_callback=None) -> Dict[str, Any]:
        """对文档进行重排序。

        Args:
            query: 查询语句。
            documents: 文档列表。
            thinking_callback: 思考过程回调函数。

        Returns:
            包含重排序结果的字典。
        """
        if not documents:
            _logger.debug("【rerank】文档列表为空")
            return {"success": True, "documents": [], "error": ""}

        if thinking_callback:
            await thinking_callback(
                {
                    "type": "thinking",
                    "stage": "reorder",
                    "content": f"正在计算 {len(documents)} 个文档的相关性分数...",
                }
            )

        _logger.debug("【rerank】开始格式化 %d 个文档", len(documents))
        pairs = await self._format_pairs(query, documents)

        _logger.debug("【rerank】开始计算 %d 个文档的分数", len(pairs))
        scores = await self._compute_scores(pairs)

        scored_documents = [{"document": doc, "similarity": float(score)} for doc, score in zip(documents, scores)]

        for i, (doc, score) in enumerate(zip(documents, scores), 1):
            preview = doc[:50] + "..." if len(doc) > 50 else doc
            _logger.info("【rerank】文档 #%d 相似度: %.4f | 预览: %s", i, float(score), preview)

        if thinking_callback:
            score_details = [
                {
                    "index": i,
                    "score": round(float(score), 4),
                    "preview": doc[:100] + "..." if len(doc) > 100 else doc,
                }
                for i, (doc, score) in enumerate(zip(documents, scores), 1)
            ]
            await thinking_callback(
                {
                    "type": "thinking",
                    "stage": "reorder",
                    "content": f"已计算完成 {len(documents)} 个文档的相关性分数，按分数降序排序",
                    "details": {"scores": score_details},
                }
            )

        sorted_docs = sorted(scored_documents, key=lambda x: x["similarity"], reverse=True)
        _logger.info("【rerank】重排序完成，返回 %d 个文档", len(sorted_docs))
        return {"success": True, "documents": sorted_docs, "error": ""}
