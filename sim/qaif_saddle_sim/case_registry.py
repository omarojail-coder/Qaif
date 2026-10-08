"""Evidence registry for optional case-inspired paired runs.

Cards constrain provenance only. They do not provide physical forcing values.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("case_registry.json")


def load_case(case_id: str, event_type: str) -> dict[str, object]:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("inspired_by_case_id must be a nonempty string")
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if registry.get("schema_version") != "1":
        raise ValueError("unsupported case registry schema")
    matches = [case for case in registry["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate case_id: {case_id}")
    case = matches[0]
    if event_type not in case["allowed_event_types"]:
        raise ValueError(f"case {case_id} does not support event_type {event_type}")
    return case
