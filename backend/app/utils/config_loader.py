import os
from dotenv import load_dotenv

from app.utils.logger import get_logger

load_dotenv()


class ConfigLoader:
    """Loads environment-driven configuration for LLM backends.

    Reads .env once at import time. Provides typed accessors for
    ALIYUN (DashScope) and OLLAMA (local) connection parameters.
    """

    def __init__(self):
        self._logger = get_logger("ConfigLoader")

    @property
    def llm_type(self) -> str:
        """Active LLM backend: 'ALIYUN' or 'OLLAMA'."""
        return os.getenv("LLM_TYPE", "ALIYUN").upper()

    def get_llm_config(self) -> dict:
        """Return a nested dict with aliyun/ollama connection settings.

        Returns:
            {"type": "ALIYUN", "aliyun": {...}, "ollama": {...}}
        """
        cfg = {
            "type": self.llm_type,
            "aliyun": {
                "api_key": os.getenv("ALIYUN_ACCESS_KEY_SECRET"),
                "model": os.getenv("ALIYUN_MODEL_NAME", "qwen3-max"),
                "base_url": os.getenv(
                    "ALIYUN_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
            },
            "ollama": {
                "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                "model": os.getenv("OLLAMA_MODEL_NAME", "qwen3.5:0.8b"),
            },
        }
        self._logger.debug("Loaded LLM config: type=%s", cfg["type"])
        return cfg


config_loader = ConfigLoader()
