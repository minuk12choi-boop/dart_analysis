import os


class MissingDartApiKeyError(RuntimeError):
    """Raised when DART_API_KEY is unavailable in environment variables."""


def get_dart_api_key() -> str:
    value = os.getenv("DART_API_KEY", "").strip()
    if not value:
        raise MissingDartApiKeyError(
            "DART_API_KEY 환경변수가 설정되지 않았습니다. "
            "실행 전에 환경변수를 설정해 주세요."
        )
    return value
