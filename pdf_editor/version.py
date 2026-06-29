"""Application version — single source of truth."""

__version__ = "1.0.3"

APP_NAME = "Tiny PDF Editor"

AUTHOR_URL = (
    "https://note4all.tistory.com/category/"
    "%EC%86%8C%ED%94%84%ED%8A%B8%EC%9B%A8%EC%96%B4%20%EC%97%B0%EA%B5%AC%EC%86%8C/"
    "TIny%20PDF%20Editor"
)
AUTHOR_LINK_TEXT = "https://note4all.tistory.com"


def version_label() -> str:
    return f"v{__version__}"


def titled_name() -> str:
    return f"{APP_NAME} {version_label()}"


def release_base_name() -> str:
    """Portable build folder/exe prefix (e.g. ``Tiny PDF Editor v1.0.3``)."""
    return f"{APP_NAME} {version_label()}"
