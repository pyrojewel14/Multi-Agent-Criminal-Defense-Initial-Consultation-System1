from app.utils.logger import get_logger


class DisclaimerService:
    DISCLAIMER_PREFIX = (
        "本内容为智能辅助生成，仅供参考，待律师确认后生效。\n\n"
    )

    def __init__(self):
        self._logger = get_logger("Disclaimer")

    def inject(self, content: str) -> str:
        if content.startswith(self.DISCLAIMER_PREFIX):
            self._logger.debug("Disclaimer already present, skipping injection")
            return content
        self._logger.debug("Injecting disclaimer prefix")
        return self.DISCLAIMER_PREFIX + content


disclaimer = DisclaimerService()
DISCLAIMER_PREFIX = DisclaimerService.DISCLAIMER_PREFIX
