"""Dynamic parser for Freya Bank briefs.

Extracts operational rules, bank holidays, deadline calculations,
identity fields, and outcome tables from any specification or raw bank memo.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def parse_brief_metadata(brief_text: str, openapi_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extracts operational policies and tables from brief text and openapi schema."""

    # 1. Holidays (ISO YYYY-MM-DD format)
    holidays = sorted(list(set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", brief_text))))

    # 2. Deadlines table & rules
    deadlines = []
    deadline_match = re.search(
        r"\|\s*`?days_late`?\s*\|\s*Band\s*\|\s*Deadline\s*\|\s*Persuasion attempts\s*\|\n\|[-| ]+\|\n((?:\|[^\n]+\|\n?)+)",
        brief_text,
        re.IGNORECASE,
    )
    if deadline_match:
        for row in deadline_match.group(1).strip().split("\n"):
            cols = [c.strip(" `") for c in row.split("|")[1:-1]]
            if len(cols) >= 4:
                deadlines.append({
                    "days_late": cols[0],
                    "band": cols[1],
                    "deadline": cols[2],
                    "attempts": cols[3],
                })

    # 3. Outcome & Reason Table
    outcomes = []
    outcome_match = re.search(
        r"\|\s*Outcome\s*\|\s*Reason\s*\|\s*When\s*\|\n\|[-| ]+\|\n((?:\|[^\n]+\|\n?)+)",
        brief_text,
        re.IGNORECASE,
    )
    if outcome_match:
        for row in outcome_match.group(1).strip().split("\n"):
            cols = [c.strip(" `") for c in row.split("|")[1:-1]]
            if len(cols) >= 3:
                outcomes.append({
                    "outcome": cols[0],
                    "reason": cols[1],
                    "when": cols[2],
                })

    # 4. Identity questions extraction
    identity_fields = []
    if openapi_spec:
        try:
            vi = openapi_spec.get("paths", {}).get("/verify_identity", {}).get("post", {})
            schema = vi.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            props = schema.get("properties", {})
            if "field" in props and "enum" in props["field"]:
                identity_fields = props["field"]["enum"]
        except Exception:
            pass

    if not identity_fields:
        # Fallback to standard identity fields if not in openapi
        identity_fields = ["date_of_birth", "phone_last4"]

    # 5. Multi-product mode detection
    is_multi = (
        ("brief b" in brief_text.lower() or
         "up to three products" in brief_text.lower() or
         "three products" in brief_text.lower() or
         "multiple products" in brief_text.lower() or
         "multi-product" in brief_text.lower())
        and "never uses add_note" not in brief_text.lower()
    )

    return {
        "holidays": holidays,
        "deadlines": deadlines,
        "outcomes": outcomes,
        "identity_fields": identity_fields,
        "is_multi_product": is_multi,
    }
