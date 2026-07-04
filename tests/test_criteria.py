import pytest

from graider.criteria import (
    load_criteria_dir,
    parse_criteria,
    released_cutoff,
    split_by_cutoff,
)
from graider.errors import GraiderError

DOC = """# Project Brief
Build a thing.

## 1. Version control
Commit often.

## 2. Testing
Write tests.

## 3. Docs
Explain it.
"""


def test_parse_items_in_order():
    c = parse_criteria(DOC)
    assert [i.id for i in c.items] == ["1", "2", "3"]
    assert [i.title for i in c.items] == ["Version control", "Testing", "Docs"]
    assert c.items[0].order == 1
    assert "Build a thing." in c.brief


def test_parse_slug_id_when_unnumbered():
    c = parse_criteria("## Version Control\nx\n")
    assert c.items[0].id == "version-control"


def test_split_by_position():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, 2)
    assert [i.id for i in ins] == ["1", "2"]
    assert [i.id for i in out] == ["3"]


def test_split_by_id():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, "2")
    assert len(ins) == 2 and len(out) == 1


def test_split_none_is_all():
    c = parse_criteria(DOC)
    ins, out = split_by_cutoff(c.items, None)
    assert len(ins) == 3 and out == []


def test_unknown_cutoff_raises():
    c = parse_criteria(DOC)
    with pytest.raises(GraiderError):
        split_by_cutoff(c.items, "nope")


def test_load_dir_and_released(tmp_path):
    (tmp_path / "criteria.md").write_text(DOC)
    (tmp_path / "graider-criteria.yml").write_text("released_up_to: 1\n")
    c = load_criteria_dir(tmp_path)
    assert len(c.items) == 3
    assert released_cutoff(tmp_path) == 1


def test_parse_levels_block():
    from graider.criteria import parse_criteria

    text = (
        "Brief.\n\n"
        "## 1. Error handling\n"
        "Handles bad input.\n\n"
        "### Levels\n"
        "- emerging: crashes\n"
        "- developing: catches some\n"
        "- proficient: validates all documented cases\n"
        "- exemplary: proficient plus recovery\n"
    )
    crit = parse_criteria(text)
    item = crit.items[0]
    assert item.levels["proficient"].startswith("validates")
    assert "### Levels" not in item.body
    assert item.body.strip() == "Handles bad input."
