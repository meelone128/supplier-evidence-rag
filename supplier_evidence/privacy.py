from __future__ import annotations

import re
from pathlib import Path


_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\d\- ]{7,}\d)(?!\d)"),
    "id_number": re.compile(r"\b\d{17}[0-9Xx]\b"),
    "bank_account": re.compile(r"\b(?:\d[ -]?){16,19}\b"),
}


def scan_sensitive_data(filename: str, data: bytes) -> dict[str, object]:
    """Best-effort preflight for text-like files.

    This is a safety reminder, not a claim that a file is fully anonymised.
    Binary Office/PDF files still require the uploader's explicit review.
    Only counts and redacted samples are stored; raw matches are never written
    to the audit log or returned to the frontend.
    """

    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".csv"}:
        return {
            "scanned": False,
            "reason": "二进制文档需人工确认脱敏状态",
            "matches": {},
            "requires_confirmation": True,
        }

    text = data.decode("utf-8", errors="ignore")
    matches: dict[str, int] = {}
    for label, pattern in _PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            matches[label] = count
    return {
        "scanned": True,
        "reason": "检测结果仅作上传前提醒，不能替代人工脱敏复核",
        "matches": matches,
        "requires_confirmation": bool(matches),
    }
