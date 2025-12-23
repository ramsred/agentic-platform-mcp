from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple


def _to_source_text(tool_result: Dict[str, Any], max_chars: int = 8000) -> str:
    """
    Convert tool output into canonical text for summarization.
    Input is expected to be a typed, schema-validated payload.
    """
    try:
        src = json.dumps(tool_result, ensure_ascii=False, indent=2)
    except Exception:
        src = str(tool_result)

    if len(src) > max_chars:
        src = src[:max_chars] + "\n...[TRUNCATED]..."

    return src

def build_summarizer_messages(source_text: str) -> List[Dict[str, str]]:
    """
    The model MUST produce JSON only, and MUST include evidence quotes that are
    exact substrings of source_text.
    """
    system = (
        "You are a summarizer that must be strictly grounded.\n"
        "Rules:\n"
        "1) Output ONLY a JSON object (no extra text).\n"
        "2) Every bullet MUST include an 'evidence' field that is an EXACT substring "
        "copied from the provided SOURCE.\n"
        "3) Do NOT add any facts not present in the SOURCE.\n"
        "4) Keep bullets short.\n"
        "Schema:\n"
        "{\n"
        '  "type": "summary",\n'
        '  "bullets": [{"claim": "...", "evidence": "..."}],\n'
        '  "risks": [{"claim": "...", "evidence": "..."}],\n'
        '  "recommendations": [{"claim": "...", "evidence": "..."}]\n'
        "}\n"
    )

    user = (
        "SOURCE (you may ONLY use this text):\n"
        f"{source_text}\n\n"
        "Return a grounded summary in the required JSON schema."
    )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class GroundingError(Exception):
    pass


def validate_grounded_summary(summary: Dict[str, Any], source_text: str) -> None:
    if not isinstance(summary, dict):
        raise GroundingError("Summary must be a JSON object.")

    if summary.get("type") != "summary":
        raise GroundingError("Summary.type must be 'summary'.")

    for section in ("bullets", "risks", "recommendations"):
        items = summary.get(section)
        if not isinstance(items, list):
            raise GroundingError(f"{section} must be a list.")

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise GroundingError(f"{section}[{i}] must be an object.")
            claim = item.get("claim")
            ev = item.get("evidence")
            if not isinstance(claim, str) or not claim.strip():
                raise GroundingError(f"{section}[{i}].claim must be a non-empty string.")
            if not isinstance(ev, str) or not ev.strip():
                raise GroundingError(f"{section}[{i}].evidence must be a non-empty string.")
            # HARD GROUNDING: evidence must be exact substring of SOURCE
            if ev not in source_text:
                raise GroundingError(
                    f"{section}[{i}] evidence not found verbatim in SOURCE."
                )