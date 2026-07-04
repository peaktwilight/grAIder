"""Anchor (benchmark) submissions: teacher-graded exemplars for calibration."""

from __future__ import annotations

from pathlib import Path

import yaml

from graider.models import Anchor, CriterionVerdict


def anchors_path(criteria_dir: Path) -> Path:
    return criteria_dir / "anchors.yml"


def load_anchors(criteria_dir: Path) -> list[Anchor]:
    path = anchors_path(criteria_dir)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    if not isinstance(data, list):
        return []
    anchors: list[Anchor] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("name"):
            levels = entry.get("levels") or {}
            anchors.append(
                Anchor(
                    name=str(entry["name"]),
                    levels={str(k): str(v) for k, v in levels.items()},
                    note=str(entry.get("note", "")),
                )
            )
    return anchors


def save_anchor(criteria_dir: Path, anchor: Anchor) -> None:
    """Add/replace an anchor by name and write anchors.yml."""
    kept = [a for a in load_anchors(criteria_dir) if a.name != anchor.name]
    kept.append(anchor)
    anchors_path(criteria_dir).write_text(
        yaml.safe_dump([a.model_dump() for a in kept], sort_keys=False), encoding="utf-8"
    )


def agreement(anchor: Anchor, verdicts: list[CriterionVerdict]) -> tuple[int, int, list[str]]:
    """Compare teacher anchor levels to model verdicts: (agree, total, disagreements)."""
    by_id = {v.id: v.level.value for v in verdicts}
    agree = 0
    total = 0
    disagreements: list[str] = []
    for cid, teacher_level in anchor.levels.items():
        if cid not in by_id:
            continue
        total += 1
        if by_id[cid] == teacher_level:
            agree += 1
        else:
            disagreements.append(f"criterion {cid}: teacher={teacher_level}, model={by_id[cid]}")
    return agree, total, disagreements
