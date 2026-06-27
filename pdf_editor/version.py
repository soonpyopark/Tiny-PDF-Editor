"""Application version — single source of truth."""

__version__ = "1.0.1"

APP_NAME = "Tiny PDF Editor"


def version_label() -> str:
    return f"v{__version__}"


def titled_name() -> str:
    return f"{APP_NAME} {version_label()}"


def release_base_name() -> str:
    """Portable build folder/exe prefix (e.g. ``Tiny PDF Editor v1.0.1``)."""
    return f"{APP_NAME} {version_label()}"
