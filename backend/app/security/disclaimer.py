DISCLAIMER_PREFIX = "本内容为智能辅助生成，仅供参考，待律师确认后生效。\n\n"


def inject_disclaimer(content: str) -> str:
    if not content.startswith(DISCLAIMER_PREFIX):
        return DISCLAIMER_PREFIX + content
    return content
