"""Phorapter error hierarchy.

Every error carries a stable machine-readable ``code`` that surfaces unchanged
through the REST error envelope and MCP error messages, so clients can act on
codes rather than parse prose.
"""

from __future__ import annotations


class PhorapterError(Exception):
    """Base class for all phorapter errors."""

    code: str = "INTERNAL"


class GridError(PhorapterError):
    """The slicing grid is invalid (not ascending, or the divisibility chain is broken)."""

    code = "INVALID_GRID"


class SlicingError(PhorapterError):
    """A document cannot be sliced (missing id, non-text input, or unencodable content)."""

    code = "SLICING_ERROR"


class TokenizerError(PhorapterError):
    """The requested token counter is unknown or unavailable."""

    code = "UNKNOWN_TOKENIZER"
