"""Low-cost rules and fingerprinting used before vector or LLM calls."""
import re


_ROUTINE = re.compile(
    r"(?:\bhealth(?:check)?\b.{0,32}\b(?:ok|healthy|passed|succeeded)\b"
    r"|\b(?:GET|HEAD)\s+/(?:health|ready|live)(?:\s|$).{0,12}\b2\d\d\b"
    r"|\bheartbeat\b.{0,24}\b(?:ok|healthy|received|success(?:ful)?)\b"
    r"|\b(?:startup|readiness|liveness) probe passed\b"
    r"|\b(?:debug|trace)\b|\bINFO\b.*\b(?:started|completed|succeeded)\b)",
    re.IGNORECASE,
)
_CRITICAL = re.compile(
    r"\b(?:fatal|critical|panic|out of memory|oom killed|disk full|no space left on device|"
    r"data corruption|database corruption|kernel panic|data loss)\b",
    re.IGNORECASE,
)
_ERROR = re.compile(
    r"\b(?:error|exception|failed|failure|timeout|timed out|connection refused|"
    r"unavailable|traceback|segmentation fault)\b",
    re.IGNORECASE,
)

_VARIABLES = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?Z?\b", re.I), "<timestamp>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b\d+\b"), "<n>"),
)


def fingerprint(message):
    """Normalize common per-event values so similar lines share a group."""
    normalized = message.strip().lower()
    for pattern, replacement in _VARIABLES:
        normalized = pattern.sub(replacement, normalized)
    return " ".join(normalized.split())


def triage(message):
    """Return a routing decision without calling an embedding or chat model."""
    if _CRITICAL.search(message):
        return {"route": "llm", "severity": "critical", "anomaly": True,
                "reason": "Critical failure pattern; requesting model recommendations."}
    if _ROUTINE.search(message) and not _ERROR.search(message):
        return {"route": "filter", "severity": "low", "anomaly": False,
                "reason": "Routine health, probe, debug, or successful informational log."}
    if _ERROR.search(message):
        return {"route": "rules", "severity": "high", "anomaly": True,
                "reason": "Matched a known error, failure, timeout, or exception pattern."}
    return {"route": "llm", "severity": "uncertain", "anomaly": None,
            "reason": "No deterministic rule confidently classified this log group."}
