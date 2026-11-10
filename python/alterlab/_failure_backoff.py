"""Parsing for the repeat-failure back-off 429 (``error: "repeat_failure_backoff"``).

The API returns this uncharged 429 when the same request failed the same way
several times in a row. Its ``detail`` extends the canonical rate-limit detail
with ``consecutive_failures``, ``outcome_class``, ``failure_code`` and ``hint``.
"""

from typing import Any, Optional, Tuple


def parse_failure_backoff_detail(
    detail: Any,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return ``(consecutive_failures, outcome_class, failure_code)`` from ``detail``.

    Each value is ``None`` when ``detail`` is not a dict or the field is
    missing or of the wrong type.
    """
    if not isinstance(detail, dict):
        return None, None, None
    count = detail.get("consecutive_failures")
    if not isinstance(count, int) or isinstance(count, bool):
        count = None
    outcome_class = detail.get("outcome_class")
    if not isinstance(outcome_class, str):
        outcome_class = None
    failure_code = detail.get("failure_code")
    if not isinstance(failure_code, str):
        failure_code = None
    return count, outcome_class, failure_code
