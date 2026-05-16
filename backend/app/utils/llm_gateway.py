from langchain_core.messages import SystemMessage, HumanMessage

from app.utils.config_loader import config_loader
from app.utils.logger import get_logger


class LLMGateway:
    def __init__(self):
        self._config = config_loader.get_llm_config()
        self._logger = get_logger("LLMGateway")
        self._logger.info(
            "LLM Gateway initialized: type=%s, model=%s",
            self._config["type"],
            self._config[self._config["type"].lower()]["model"],
        )

    def _create_model(self, temperature: float):
        if self._config["type"] == "OLLAMA":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=self._config["ollama"]["model"],
                base_url=self._config["ollama"]["base_url"],
                temperature=temperature,
            )

        from langchain_community.chat_models import ChatTongyi

        return ChatTongyi(
            model=self._config["aliyun"]["model"],
            api_key=self._config["aliyun"]["api_key"],
            base_url=self._config["aliyun"]["base_url"],
            temperature=temperature,
        )

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        is_legal: bool = False,
    ) -> str:
        actual_temp = 0.0 if is_legal else temperature
        self._logger.debug(
            "LLM call: temp=%.2f, is_legal=%s, msg_len=%d",
            actual_temp, is_legal, len(user_message),
        )

        model = self._create_model(actual_temp)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        response = await model.ainvoke(messages)
        self._logger.debug("LLM response: len=%d", len(response.content))
        return response.content


llm_gateway = LLMGateway()
