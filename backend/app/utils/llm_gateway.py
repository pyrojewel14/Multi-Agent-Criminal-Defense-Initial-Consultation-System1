from langchain_core.messages import SystemMessage, HumanMessage

from app.utils.factory import chat_model_factory
from app.utils.logger import get_logger
from app.errors.exceptions import LLMServiceException, LLMTimeoutException


class LLMGateway:
    """统一 LLM 调用入口。

    支持 ALIYUN（DashScope / Qwen3）和 OLLAMA（本地）两种后端，
    通过 LLM_TYPE 环境变量切换。法律查询强制使用 temperature=0。
    """

    def __init__(self):
        """初始化 LLM 网关。"""
        self._logger = get_logger("LLMGateway")
        self._logger.info("【__init__】LLM 网关初始化完成")

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        is_legal: bool = False,
    ) -> str:
        """调用 LLM 并返回文本响应。

        Args:
            system_prompt: 系统的指令内容。
            user_message: 用户的输入文本。
            temperature: 采样温度 (0.0-1.0)，法律场景强制为 0。
            is_legal: 是否为法律场景，为 True 时强制使用 temperature=0。

        Returns:
            模型的文本输出。

        Raises:
            LLMTimeoutException: 上游 API 超时。
            LLMServiceException: 上游 API 返回错误。
        """
        actual_temp = 0.0 if is_legal else temperature
        self._logger.debug(
            "【generate】LLM 调用: temp=%.2f, is_legal=%s, msg_len=%d",
            actual_temp, is_legal, len(user_message),
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        try:
            model = chat_model_factory.create_model(actual_temp)
            response = await model.ainvoke(messages)
        except TimeoutError as e:
            self._logger.error("【generate】LLM 超时: %s", e)
            raise LLMTimeoutException(detail=str(e)) from e
        except Exception as e:
            self._logger.error("【generate】LLM 服务错误: %s", e)
            raise LLMServiceException(detail=str(e)) from e

        content = response.content
        self._logger.debug("【generate】LLM 响应: len=%d", len(content))
        return content


llm_gateway = LLMGateway()
