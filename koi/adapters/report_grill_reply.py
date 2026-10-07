"""Parse a completed report setup proposal from an agent reply."""

from __future__ import annotations

import json
import re

def parse_reply(text: str) -> tuple[str, dict | None]:
    matches = list(re.finditer(r"```report-setup\s*\n(.*?)\n```", text, re.S))
    if len(matches) != 1:
        return text, None
    match = matches[0]
    try:
        proposal = json.loads(match[1])
    except (ValueError, TypeError):
        return text, None
    if not isinstance(proposal, dict) or set(proposal) != {"goal", "setup", "tasks"}:
        return text, None
    if any(not isinstance(v, str) or not v.strip() for v in proposal.values()):
        return text, None
    return (text[:match.start()] + text[match.end():]).strip() or "Постановка подготовлена. Проверьте предложение перед применением.", proposal
