"""Standalone annotation format and target masking; no simulator or model training.

Truth and observation files are deliberately not inputs to this module. Signal
labels must be supplied using a separately reviewed label policy.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

VERSION = "2.1"
SIGNALS = (
    "mechanical_anomaly", "thermal_anomaly", "wetness_anomaly", "h2s_anomaly"
)
STATES = {"present", "absent", "unknown"}
QUALITY_STATES = {"adequate", "degraded", "insufficient"}
SOURCE_ROLES = {"format_example", "research_annotation", "measured_annotation"}


def _keys(value: object, expected: set[str], where: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{where} requires exactly {sorted(expected)}")


def _text(value: object, where: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a nonempty string")


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be numeric")
    if not math.isfinite(value):
        raise ValueError(f"{where} must be finite")
    return float(value)


def validate_annotation(row: object) -> None:
    """Reject incomplete, extra, invalid, or ambiguous annotation fields."""
    _keys(row, {"schema_version", "record_id", "timestamp_s", "source_role",
                "label_policy_id", "signals", "quality"}, "annotation")
    if row["schema_version"] != VERSION:
        raise ValueError("unsupported annotation schema_version")
    for key in ("record_id", "label_policy_id"):
        _text(row[key], key)
    if _finite(row["timestamp_s"], "timestamp_s") < 0:
        raise ValueError("timestamp_s must be nonnegative")
    if not isinstance(row["source_role"], str) or row["source_role"] not in SOURCE_ROLES:
        raise ValueError("invalid source_role")
    _keys(row["signals"], set(SIGNALS), "signals")
    for signal in SIGNALS:
        item = row["signals"][signal]
        _keys(item, {"state", "reason", "evidence_refs"}, signal)
        if not isinstance(item["state"], str) or item["state"] not in STATES:
            raise ValueError(f"invalid state for {signal}")
        _text(item["reason"], f"{signal}.reason")
        if not isinstance(item["evidence_refs"], list):
            raise ValueError(f"{signal}.evidence_refs must be a list")
        for ref in item["evidence_refs"]:
            _text(ref, f"{signal}.evidence_refs item")
    _keys(row["quality"], {"status", "reason"}, "quality")
    status = row["quality"]["status"]
    if not isinstance(status, str) or status not in QUALITY_STATES:
        raise ValueError("invalid quality status")
    _text(row["quality"]["reason"], "quality.reason")


def unknown_annotation(record_id: str, timestamp_s: float, *, source_role: str,
                       label_policy_id: str, quality_status: str, reason: str) -> dict:
    """Create explicit unknowns, never automatic negative signal labels."""
    row = {
        "schema_version": VERSION,
        "record_id": record_id,
        "timestamp_s": timestamp_s,
        "source_role": source_role,
        "label_policy_id": label_policy_id,
        "signals": {
            name: {"state": "unknown", "reason": reason, "evidence_refs": []}
            for name in SIGNALS
        },
        "quality": {"status": quality_status, "reason": reason},
    }
    validate_annotation(row)
    return row


def load_annotations(path: str | Path) -> list[dict]:
    """Load validated JSONL annotations without reading features or truth."""
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate_annotation(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid annotation at line {number}: {exc}") from exc
        rows.append(row)
    return rows


@dataclass(frozen=True)
class EncodedTargets:
    record_ids: tuple[str, ...]
    values: tuple[tuple[float | None, ...], ...]
    known_mask: tuple[tuple[bool, ...], ...]
    training_allowed: bool


def encode_annotations(rows: list[dict], *, for_training: bool = True) -> EncodedTargets:
    """Present=1, absent=0, unknown=None with a false mask.

    The default training route rejects format examples. for_training=False is
    for reviewing the format and arithmetic, not permission to train on examples.
    Quality is retained in annotation records; it is not a fifth fault class.
    A quality policy has not been implemented and does not infer these targets.
    """
    ids, values, masks = [], [], []
    for row in rows:
        validate_annotation(row)
        if row["record_id"] in ids:
            raise ValueError("duplicate record_id in target batch")
        if for_training and row["source_role"] == "format_example":
            raise ValueError("format examples are excluded from model training")
        targets = tuple({"present": 1.0, "absent": 0.0, "unknown": None}[
            row["signals"][signal]["state"]] for signal in SIGNALS)
        ids.append(row["record_id"])
        values.append(targets)
        masks.append(tuple(value is not None for value in targets))
    result = EncodedTargets(tuple(ids), tuple(values), tuple(masks), for_training)
    _validate_targets(result)
    return result


def _validate_targets(targets: EncodedTargets) -> None:
    if not isinstance(targets.training_allowed, bool):
        raise ValueError("training_allowed must be boolean")
    if len(targets.record_ids) != len(targets.values) or len(targets.values) != len(targets.known_mask):
        raise ValueError("target batch lengths differ")
    if len(set(targets.record_ids)) != len(targets.record_ids):
        raise ValueError("duplicate record_id in target batch")
    for values, mask in zip(targets.values, targets.known_mask):
        if len(values) != len(SIGNALS) or len(mask) != len(SIGNALS):
            raise ValueError("each target row requires all four signals")
        for value, known in zip(values, mask):
            if not isinstance(known, bool) or known != (value is not None):
                raise ValueError("unknown must be None with a false mask")
            if known and (_finite(value, "known target") not in (0.0, 1.0)):
                raise ValueError("known target must be 0 or 1")


def head_training_view(targets: EncodedTargets, signal: str) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Indices and binary labels for one future XGBoost head, unknowns removed.

    No feature matrix is built here. A trainer must apply these same indices to
    its separately prepared feature rows. Empty/one-class heads require review.
    """
    _validate_targets(targets)
    if not targets.training_allowed:
        raise ValueError("preview targets cannot be passed to the training adapter")
    if signal not in SIGNALS:
        raise ValueError("unknown signal head")
    column = SIGNALS.index(signal)
    indices = tuple(i for i, row in enumerate(targets.known_mask) if row[column])
    labels = tuple(targets.values[i][column] for i in indices)
    return indices, labels


def masked_binary_cross_entropy(logits: list[list[float]], targets: EncodedTargets) -> dict:
    """Numerical reference for future sequence training; not a training loop.

    Compute loss only at known positions, before evaluating unknown logits.
    No-known-label batches return loss=None, not an apparent perfect loss of 0.
    Future framework integration must preserve this masking and its gradients.
    """
    _validate_targets(targets)
    if len(logits) != len(targets.values):
        raise ValueError("logit/target batch sizes differ")
    losses = {signal: [] for signal in SIGNALS}
    for prediction, values, mask in zip(logits, targets.values, targets.known_mask):
        if len(prediction) != len(SIGNALS):
            raise ValueError("logit row requires all four signals")
        for column, signal in enumerate(SIGNALS):
            if not mask[column]:
                continue
            x = _finite(prediction[column], "known logit")
            y = values[column]
            losses[signal].append(max(x, 0.0) - x * y + math.log1p(math.exp(-abs(x))))
    total = [value for values in losses.values() for value in values]
    return {
        "loss": math.fsum(total) / len(total) if total else None,
        "known_label_count": len(total),
        "by_signal": {
            signal: {"known_label_count": len(values),
                     "loss": math.fsum(values) / len(values) if values else None}
            for signal, values in losses.items()
        },
        "implementation": "numerical_reference_only",
    }
