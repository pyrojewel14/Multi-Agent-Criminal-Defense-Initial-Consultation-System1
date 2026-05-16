from app.utils.logger import get_logger


class DisclaimerService:
    """Injects the mandatory legal disclaimer prefix into agent output."""

    DISCLAIMER_PREFIX = (
        "本内容为智能辅助生成，仅供参考，待律师确认后生效。\n\n"
    )

    def __init__(self):
        self._logger = get_logger("Disclaimer")

    def inject(self, content: str) -> str:
        """Ensure the disclaimer prefix is present at the start of content.

        If the prefix already exists, the content is returned unchanged
        (idempotent). Otherwise, the prefix is prepended.

        Args:
            content: The raw agent output text.

        Returns:
            Content with the disclaimer prefix guaranteed at the start.
        """
        if content.startswith(self.DISCLAIMER_PREFIX):
            self._logger.debug("Disclaimer already present, skipping injection")
            return content
        self._logger.debug("Injecting disclaimer prefix")
        return self.DISCLAIMER_PREFIX + content


disclaimer = DisclaimerService()
DISCLAIMER_PREFIX = DisclaimerService.DISCLAIMER_PREFIX
