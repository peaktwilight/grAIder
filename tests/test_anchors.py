from graider.authoring.anchors import agreement, load_anchors, save_anchor
from graider.models import Anchor, CriterionVerdict
from graider.models import PerformanceLevel as P


def test_save_and_load_anchor(tmp_path):
    save_anchor(tmp_path, Anchor(name="a1", levels={"1": "proficient"}, note="ok"))
    save_anchor(tmp_path, Anchor(name="a2", levels={"2": "emerging"}))
    anchors = load_anchors(tmp_path)
    assert {a.name for a in anchors} == {"a1", "a2"}
    save_anchor(tmp_path, Anchor(name="a1", levels={"1": "exemplary"}))  # replace by name
    a1 = next(a for a in load_anchors(tmp_path) if a.name == "a1")
    assert a1.levels == {"1": "exemplary"}


def test_agreement():
    anchor = Anchor(name="a", levels={"1": "proficient", "2": "emerging"})
    verdicts = [
        CriterionVerdict(id="1", title="A", level=P.PROFICIENT, evidence=[], comment=""),
        CriterionVerdict(id="2", title="B", level=P.DEVELOPING, evidence=[], comment=""),
    ]
    agree, total, disagreements = agreement(anchor, verdicts)
    assert (agree, total) == (1, 2)
    assert len(disagreements) == 1 and "criterion 2" in disagreements[0]
