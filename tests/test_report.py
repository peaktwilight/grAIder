import csv
import json

from graider.models import CriterionVerdict, GradeResult, ReviewResult
from graider.report.build import (
    load_grades,
    load_reviews,
    render_report,
    summary_row,
    write_csv,
)


def _grade():
    return GradeResult(
        project="brave-otter",
        template="python",
        qlty_issues=1,
        qlty_smells=2,
        tests_passed=3,
        tests_failed=0,
        coverage_percent=88.0,
    )


def _review():
    return ReviewResult(
        project="brave-otter",
        head_sha="abc",
        model="claude-opus-4-8",
        cutoff="2",
        overall_summary="Good work.",
        criteria=[
            CriterionVerdict(  # type: ignore
                id="1",
                title="VCS",
                met=True,  # type: ignore
                evidence=["a.py:1 — ok"],
                comment="clean",
            ),
            CriterionVerdict(  # type: ignore
                id="2",
                title="Tests",
                met=False,  # type: ignore
                evidence=[],
                comment="add more",
                next_step="write some tests (topic 5)",
            ),
        ],
    )


def test_render_includes_both():
    md = render_report(_grade(), _review(), url="https://gl/x")
    assert "# brave-otter" in md
    assert "88.0%" in md
    assert "1/2 criteria met" in md
    assert "https://gl/x" in md
    assert "a.py:1 — ok" in md


def test_render_grade_only():
    md = render_report(_grade(), None)
    assert "## Metrics" in md
    assert "## Review" not in md


def test_summary_row():
    from graider.report.build import CSV_COLUMNS

    row = summary_row(_grade(), _review(), url="u")
    assert row["criteria_met"] == 1 and row["criteria_total"] == 2
    assert row["coverage_percent"] == 88.0
    assert row["count_proficient"] == 1
    assert row["count_emerging"] == 1
    assert row["count_developing"] == 0
    assert row["count_exemplary"] == 0

    for name in ("count_emerging", "count_developing", "count_proficient", "count_exemplary"):
        assert name in CSV_COLUMNS

    # Grade-only project: level counts are blank, not 0 (not "reviewed with none").
    grade_only = summary_row(_grade(), None)
    for name in ("count_emerging", "count_developing", "count_proficient", "count_exemplary"):
        assert grade_only[name] == ""


def test_load_grades_list(tmp_path):
    p = tmp_path / "grade-results.json"
    p.write_text(json.dumps([_grade().model_dump()]))
    assert load_grades(p)[0].project == "brave-otter"


def test_load_reviews_single_object(tmp_path):
    p = tmp_path / "review-results.json"
    p.write_text(_review().model_dump_json())
    assert load_reviews(p)[0].project == "brave-otter"


def test_write_csv(tmp_path):
    out = tmp_path / "summary.csv"
    write_csv([summary_row(_grade(), _review())], out)
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["project"] == "brave-otter"
    assert rows[0]["criteria_met"] == "1"


def test_render_report_next_step():
    md = render_report(_grade(), _review())
    assert "### Where to next" in md
    assert "write some tests (topic 5)" in md


def test_render_report_self_assessment():
    review = _review()
    review.self_assessment = {"1": "developing"}
    md = render_report(_grade(), review)
    assert "Self" in md
    assert "developing" in md


def test_discrepancy_flagging():
    from graider.models import PerformanceLevel as P
    from graider.report.build import flag_discrepancies

    grade_bad = GradeResult(project="p", template="t", tests_passed=1, tests_failed=1)
    review_good = ReviewResult(
        project="p",
        head_sha="abc",
        model="m",
        cutoff="2",
        overall_summary="summary",
        criteria=[
            CriterionVerdict(
                id="1",
                title="A",
                level=P.PROFICIENT,
                evidence=[],
                comment="",
            )
        ],
    )
    flags = flag_discrepancies(grade_bad, review_good)
    assert len(flags) == 1
    assert "test(s) failing" in flags[0]

    md = render_report(grade_bad, review_good)
    assert "Discrepancies" in md

    grade_good = GradeResult(project="p", template="t", tests_passed=3, tests_failed=0)
    review_bad = ReviewResult(
        project="p",
        head_sha="abc",
        model="m",
        cutoff="2",
        overall_summary="summary",
        criteria=[
            CriterionVerdict(
                id="1",
                title="A",
                level=P.EMERGING,
                evidence=[],
                comment="",
            )
        ],
    )
    flags2 = flag_discrepancies(grade_good, review_bad)
    assert len(flags2) == 1
    assert "all tests pass" in flags2[0]

    md2 = render_report(grade_good, review_bad)
    assert "Discrepancies" in md2
