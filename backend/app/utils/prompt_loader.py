import yaml
from pathlib import Path

from app.utils.logger import get_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_CONFIG_PATH = PROJECT_ROOT / "app" / "config" / "prompt.yaml"


class PromptLoader:
    def __init__(self):
        self._logger = get_logger("PromptLoader")
        self._prompt_map: dict[str, str] = {}

        if not PROMPT_CONFIG_PATH.exists():
            self._logger.error(
                "Prompt config not found: %s", PROMPT_CONFIG_PATH
            )
            return

        try:
            with open(PROMPT_CONFIG_PATH, "r", encoding="utf-8") as f:
                self._prompt_map = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            self._logger.error(
                "Failed to load prompt config %s: %s", PROMPT_CONFIG_PATH, e
            )
            self._prompt_map = {}

        self._logger.debug(
            "Loaded prompt map: %d entries", len(self._prompt_map)
        )

    def load(self, name: str) -> str:
        if name not in self._prompt_map:
            self._logger.error("Prompt '%s' not found in config", name)
            raise KeyError(
                f"Prompt '{name}' not registered in {PROMPT_CONFIG_PATH}"
            )

        relative_path = self._prompt_map[name]
        full_path = PROJECT_ROOT / relative_path

        if not full_path.exists():
            self._logger.error(
                "Prompt file missing: %s (from key '%s')", full_path, name
            )
            raise FileNotFoundError(
                f"Prompt file not found: {full_path} (key: {name})"
            )

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError as e:
            self._logger.error("Failed to read prompt '%s': %s", name, e)
            raise

        self._logger.debug("Loaded prompt '%s' from %s", name, relative_path)
        return content

    def get_map(self) -> dict[str, str]:
        return dict(self._prompt_map)


prompt_loader = PromptLoader()
