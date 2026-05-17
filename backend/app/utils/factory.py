from abc import ABC, abstractmethod
from typing import Optional, List
import os
from dotenv import load_dotenv

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.errors.exceptions import LLMServiceException
from app.utils.config_loader import config_loader
from app.utils.logger import get_logger

load_dotenv()

_logger = get_logger("ModelFactory")


class DashScopeEmbeddingsWrapper(Embeddings):
    """阿里云 DashScope 嵌入模型封装。

    支持文本嵌入功能，将输入文本转换为向量表示。
    """

    def __init__(self, model_name: str = "qwen3-embedding", api_key: str = None):
        """初始化 DashScope 嵌入模型。

        Args:
            model_name: 模型名称，默认为 qwen3-embedding。
            api_key: API 密钥，如不提供则从环境变量获取。
        """
        try:
            import dashscope

            self.dashscope = dashscope
            self.dashscope.api_key = api_key or os.getenv("ALIYUN_ACCESS_KEY_SECRET")
            self.model_name = model_name
        except ImportError:
            raise ImportError("需要安装 dashscope 库: pip install dashscope")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """将多个文本转换为嵌入向量。

        Args:
            texts: 待嵌入的文本列表。

        Returns:
            嵌入向量列表，每个向量为 float 列表。
        """
        results = []
        for text in texts:
            try:
                resp = self.dashscope.TextEmbedding.call(
                    model=self.model_name, input=text
                )
            except TimeoutError as e:
                _logger.error("DashScope embedding 超时: %s", e)
                raise LLMServiceException(
                    detail=f"DashScope embedding 超时: {e}"
                ) from e
            except Exception as e:
                _logger.error("DashScope embedding 错误: %s", e)
                raise LLMServiceException(
                    detail=f"DashScope embedding 错误: {e}"
                ) from e

            if resp.status_code != 200:
                _logger.error(
                    "DashScope embedding 失败: status=%d, message=%s",
                    resp.status_code,
                    resp.message,
                )
                raise LLMServiceException(
                    detail=f"DashScope embedding 失败: {resp.message}"
                )
            results.append(resp.output["embedding"])
        return results

    def embed_query(self, text: str) -> List[float]:
        """将单个查询文本转换为嵌入向量。

        Args:
            text: 待嵌入的查询文本。

        Returns:
            嵌入向量，为 float 列表。
        """
        try:
            resp = self.dashscope.TextEmbedding.call(model=self.model_name, input=text)
        except TimeoutError as e:
            _logger.error("DashScope embedding 超时: %s", e)
            raise LLMServiceException(detail=f"DashScope embedding 超时: {e}") from e
        except Exception as e:
            _logger.error("DashScope embedding 错误: %s", e)
            raise LLMServiceException(detail=f"DashScope embedding 错误: {e}") from e

        if resp.status_code != 200:
            _logger.error(
                "DashScope embedding 失败: status=%d, message=%s",
                resp.status_code,
                resp.message,
            )
            raise LLMServiceException(
                detail=f"DashScope embedding 失败: {resp.message}"
            )
        return resp.output["embedding"]


class BaseModelFactory(ABC):
    """基础模型工厂抽象类。

    提供模型创建的标准接口和配置获取方法。
    """

    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """生成模型实例。"""

    def _get_llm_config(self) -> dict:
        """从配置加载器获取 LLM 配置。

        Returns:
            LLM 配置字典。
        """
        return config_loader.get_llm_config()


class ChatModelFactory(BaseModelFactory):
    """聊天模型工厂。

    支持阿里云百炼和 Ollama 两种后端。
    提供两种创建方式：
    1. generator() - 创建带 streaming 的模型实例（用于流式响应）
    2. create_model(temperature) - 创建带指定温度的模型实例（用于精确响应）
    """

    def generator(self, streaming: bool = True, top_p: float = 0.7) -> Optional[BaseChatModel]:
        """创建聊天模型实例（带 streaming 配置）。

        Args:
            streaming: 是否启用流式输出。
            top_p: 采样参数。

        Returns:
            聊天模型实例。
        """
        return self._create_model(streaming=streaming, top_p=top_p)

    def create_model(self, temperature: float = 0.1) -> BaseChatModel:
        """创建聊天模型实例（带指定温度，用于精确响应）。

        Args:
            temperature: 采样温度 (0.0-1.0)。

        Returns:
            配置好的聊天模型实例。
        """
        return self._create_model(temperature=temperature, streaming=False, top_p=None)

    def _create_model(
        self,
        temperature: Optional[float] = None,
        streaming: bool = False,
        top_p: Optional[float] = None,
    ) -> BaseChatModel:
        """根据配置创建聊天模型。

        Args:
            temperature: 采样温度。
            streaming: 是否启用流式输出。
            top_p: 采样参数。

        Returns:
            聊天模型实例。
        """
        config = self._get_llm_config()
        llm_type = config.get("type", "ALIYUN").upper()

        if llm_type == "OLLAMA":
            return self._create_ollama_model(config, temperature, streaming, top_p)
        return self._create_aliyun_model(config, temperature, streaming, top_p)

    def _create_ollama_model(
        self,
        config: dict,
        temperature: Optional[float],
        streaming: bool,
        top_p: Optional[float],
    ) -> BaseChatModel:
        """创建 Ollama 聊天模型。

        Args:
            config: 模型配置字典。
            temperature: 采样温度。
            streaming: 是否启用流式输出。
            top_p: 采样参数。

        Returns:
            ChatOllama 实例。
        """
        from langchain_ollama import ChatOllama

        ollama_config = config.get("ollama", {})
        model_name = ollama_config.get("model", os.getenv("OLLAMA_MODEL_NAME", "qwen3:7b"))
        base_url = ollama_config.get("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))

        _logger.info("ChatModel 使用 Ollama: model=%s, base_url=%s", model_name, base_url)

        params = {"model": model_name, "base_url": base_url}
        if temperature is not None:
            params["temperature"] = temperature
        if streaming:
            params["streaming"] = streaming
        if top_p is not None:
            params["top_p"] = top_p

        return ChatOllama(**params)

    def _create_aliyun_model(
        self,
        config: dict,
        temperature: Optional[float],
        streaming: bool,
        top_p: Optional[float],
    ) -> BaseChatModel:
        """创建阿里云百炼聊天模型。

        Args:
            config: 模型配置字典。
            temperature: 采样温度。
            streaming: 是否启用流式输出。
            top_p: 采样参数。

        Returns:
            ChatTongyi 实例。
        """
        from langchain_community.chat_models.tongyi import ChatTongyi

        aliyun_config = config.get("aliyun", {})
        model_name = aliyun_config.get("model", os.getenv("ALIYUN_MODEL_NAME", "qwen3-max"))
        api_key = aliyun_config.get("api_key", os.getenv("ALIYUN_ACCESS_KEY_SECRET"))
        base_url = aliyun_config.get("base_url", os.getenv("ALIYUN_BASE_URL"))

        _logger.info("ChatModel 使用阿里云百炼: model=%s", model_name)

        params = {"model": model_name, "api_key": api_key}
        if base_url:
            params["base_url"] = base_url
        if temperature is not None:
            params["temperature"] = temperature
        if streaming:
            params["streaming"] = streaming
        if top_p is not None:
            params["top_p"] = top_p

        return ChatTongyi(**params)


class EmbedModelFactory(BaseModelFactory):
    """嵌入模型工厂。

    支持 Ollama 和阿里云百炼两种后端。
    """

    def generator(self) -> Optional[Embeddings]:
        """根据 EMBED_MODEL_TYPE 生成对应的嵌入模型。

        Returns:
            嵌入模型实例。

        Raises:
            ValueError: 当 EMBED_MODEL_TYPE 不支持时。
        """
        embed_type = os.getenv("EMBED_MODEL_TYPE", "OLLAMA").upper()

        if embed_type == "OLLAMA":
            return self._create_ollama_embeddings()
        elif embed_type == "ALIYUN":
            return self._create_aliyun_embeddings()
        else:
            raise ValueError(f"不支持的 EMBED_MODEL_TYPE: {embed_type}，可选值: OLLAMA, ALIYUN")

    def _create_ollama_embeddings(self) -> Embeddings:
        """创建 Ollama 嵌入模型。

        Returns:
            OllamaEmbeddings 实例。
        """
        from langchain_ollama import OllamaEmbeddings

        model_name = os.getenv("TEXT_EMBEDDING_MODEL_NAME", "qwen3-embedding:0.6b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        _logger.info("EmbedModel 使用 Ollama: model=%s, base_url=%s", model_name, base_url)

        return OllamaEmbeddings(model=model_name, base_url=base_url)

    def _create_aliyun_embeddings(self) -> DashScopeEmbeddingsWrapper:
        """创建阿里云百炼嵌入模型。

        Returns:
            DashScopeEmbeddingsWrapper 实例。
        """
        model_name = os.getenv("ALIYUN_EMBED_MODEL_NAME", "qwen3-embedding")
        api_key = os.getenv("ALIYUN_ACCESS_KEY_SECRET")

        _logger.info("EmbedModel 使用阿里云百炼: model=%s", model_name)

        return DashScopeEmbeddingsWrapper(model_name=model_name, api_key=api_key)


class RerankerModelFactory(BaseModelFactory):
    """重排序模型工厂。

    已废弃，使用 CrossEncoder 模型替代。
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """生成重排序模型实例。

        Returns:
            始终返回 None，该工厂已废弃。
        """
        return None


chat_model_factory = ChatModelFactory()
embed_model_factory = EmbedModelFactory()

chat_model = chat_model_factory.generator()
embed_model = embed_model_factory.generator()
reranker_model = None
