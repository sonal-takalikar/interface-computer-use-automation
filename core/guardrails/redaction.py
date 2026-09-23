"""
Data Redaction Engine.
Sanitizes regulated financial data and credentials from logs, traces, and artifacts.
Redacts:
- US Social Security Numbers (SSN): 123-45-6789 -> ***-**-6789
- Full Bank Account Numbers: 0049-8210-91 -> ****-****-91
- Credit / Debit Card Numbers: 16 digits -> [REDACTED_PAN]
- Passwords and Tokens: token=xyz123 -> token=[REDACTED]
"""

import re
from typing import Any, Dict, List, Union


class SensitiveDataRedactor:
    """Regex-based financial PII and secret sanitizer."""

    # Patterns
    SSN_PATTERN = re.compile(r"\b(?:\d{3}-\d{2}-(\d{4}))\b")
    SSN_RAW_PATTERN = re.compile(r"\b(?:\d{9})\b")
    ACCOUNT_PATTERN = re.compile(r"\b\d{4}-\d{4}-(\d{2,4})\b")
    CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
    SECRET_PATTERN = re.compile(r"(?i)\b(api_key|token|password|secret|auth_code|override_code)\s*[=:]\s*([^\s,;\"']+)")

    @classmethod
    def redact_text(cls, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        # Redact SSN, preserving last 4 digits
        sanitized = cls.SSN_PATTERN.sub(r"***-**-\1", text)

        # Redact Account number, preserving last 2-4 digits
        sanitized = cls.ACCOUNT_PATTERN.sub(r"****-****-\1", sanitized)

        # Redact Credit Card PANs
        sanitized = cls.CARD_PATTERN.sub("[REDACTED_PAN]", sanitized)

        # Redact secrets
        sanitized = cls.SECRET_PATTERN.sub(r"\1=[REDACTED_SECRET]", sanitized)

        return sanitized

    @classmethod
    def redact_structure(cls, data: Union[Dict, List, Any]) -> Any:
        """Recursively redact strings within nested dictionaries and lists."""
        if isinstance(data, str):
            return cls.redact_text(data)
        elif isinstance(data, dict):
            return {k: cls.redact_structure(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.redact_structure(item) for item in data]
        return data
