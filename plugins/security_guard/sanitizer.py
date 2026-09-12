"""Sanitizer module for stripping injection patterns from messages.

Hardened:
- Pre-compiled regex patterns (no per-call recompilation)
- Max message length to prevent ReDoS
- Compiled patterns stored in SanitizerConfig for reuse
"""

import re
from typing import List, Optional
from injection_patterns import INJECTION_PATTERNS, MAX_MESSAGE_LENGTH


class SanitizerConfig:
    """Configuration for the sanitizer with pre-compiled patterns."""

    def __init__(self, patterns: Optional[List[str]] = None, replacement: str = "[REDACTED]"):
        if patterns is not None:
            # User-provided patterns → compile them
            self._compiled: List[re.Pattern] = [
                re.compile(p, re.IGNORECASE | re.UNICODE) for p in patterns
            ]
        else:
            # Use the pre-compiled patterns from injection_patterns
            self._compiled: List[re.Pattern] = [p for _, p in INJECTION_PATTERNS]
        self.patterns = patterns  # Keep raw patterns for introspection
        self.replacement = replacement


def sanitize_message(text: str, config: Optional[SanitizerConfig] = None) -> str:
    """Strip or replace injection patterns from a message.

    - Truncates input to ``MAX_MESSAGE_LENGTH`` to prevent ReDoS.
    - Uses pre-compiled regex patterns for performance.
    - Returns the original text if config is None and no patterns match.
    """
    if config is None:
        config = SanitizerConfig()
    if not text or not isinstance(text, str):
        return text
    # Truncate to prevent ReDoS on oversized inputs
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]
    result = text
    for compiled_pattern in config._compiled:
        result = compiled_pattern.sub(config.replacement, result)
    return result
