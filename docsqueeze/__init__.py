"""docsqueeze - token-efficient universal document reader for AI agents.

Public API:

    from docsqueeze import extract_document, Section, estimate_tokens

CLI:

    python -m docsqueeze <file> [--pages 1-5] [--max-tokens N] [--json]
"""

from .core import (
    DEFAULT_BUDGET_TOKENS,
    EXIT_OK,
    EXIT_IO,
    EXIT_PARSE,
    EXIT_SECURITY,
    EXIT_UNSUPPORTED,
    VERSION,
    DocsqueezeError,
    SecurityError,
    Section,
    UnsupportedError,
    build_output,
    estimate_tokens,
    extract_document,
    human_size,
    main,
    sanitize_text,
)

__all__ = [
    "DEFAULT_BUDGET_TOKENS",
    "EXIT_OK",
    "EXIT_IO",
    "EXIT_PARSE",
    "EXIT_SECURITY",
    "EXIT_UNSUPPORTED",
    "VERSION",
    "DocsqueezeError",
    "SecurityError",
    "Section",
    "UnsupportedError",
    "build_output",
    "estimate_tokens",
    "extract_document",
    "human_size",
    "main",
    "sanitize_text",
]
__version__ = VERSION
