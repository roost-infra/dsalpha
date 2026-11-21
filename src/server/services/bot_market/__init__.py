"""The built-in Bot market: a code-shipped catalogue plus its install journal."""

from .catalog import (
    card,
    load_catalog,
    category_label,
    category_options,
    detail,
    find_bot,
    resolve_locale,
)
from .install import (
    NameTaken,
    TemplateNotFound,
    WorkspaceFull,
    install_bot,
)

__all__ = [
    "NameTaken",
    "TemplateNotFound",
    "WorkspaceFull",
    "card",
    "load_catalog",
    "category_label",
    "category_options",
    "detail",
    "find_bot",
    "install_bot",
    "resolve_locale",
]
