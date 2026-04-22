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


def get_env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    if min_value is not None and parsed < min_value:
        return default
    return parsed


def get_env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        parsed = float(raw.strip())
    except ValueError:
        return default
    if min_value is not None and parsed < min_value:
        return default
    return parsed
