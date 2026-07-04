import json
import shutil

from graider.grading.runner import (
    _count_json_array,
    _parse_coverage_json,
    _parse_junit_many,
    _run_qlty,
)
from graider.models import GradeResult


def test_parse_junit_many_single_suite(tmp_path):
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="3" failures="1" errors="0">
    <testcase name="test1"/>
    <testcase name="test2"/>
    <testcase name="test3"/>
</testsuite>
"""
    xml_file = tmp_path / "results.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    result = GradeResult(project="p", template="python")
    _parse_junit_many([xml_file], result)
    assert result.tests_passed == 2
    assert result.tests_failed == 1
    assert not result.errors


def test_parse_junit_many_multiple_suites(tmp_path):
    xml_content1 = """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="3" failures="1" errors="0">
    <testcase name="test1"/>
</testsuite>
"""
    xml_content2 = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite tests="2" failures="0" errors="1">
        <testcase name="test2"/>
    </testsuite>
</testsuites>
"""
    f1 = tmp_path / "r1.xml"
    f2 = tmp_path / "r2.xml"
    f1.write_text(xml_content1, encoding="utf-8")
    f2.write_text(xml_content2, encoding="utf-8")

    result = GradeResult(project="p", template="python")
    _parse_junit_many([f1, f2], result)
    assert result.tests_passed == 3
    assert result.tests_failed == 2


def test_parse_junit_many_no_paths():
    result = GradeResult(project="p", template="python")
    _parse_junit_many([], result)
    assert "no test results produced" in result.errors


def test_parse_coverage_json(tmp_path):
    cov_data = {"totals": {"percent_covered": 87.534}}
    cov_file = tmp_path / "cov.json"
    cov_file.write_text(json.dumps(cov_data), encoding="utf-8")

    result = GradeResult(project="p", template="python")
    _parse_coverage_json(cov_file, result)
    assert result.coverage_percent == 87.5


def test_parse_coverage_json_invalid(tmp_path):
    cov_file = tmp_path / "cov.json"
    cov_file.write_text("invalid json", encoding="utf-8")

    result = GradeResult(project="p", template="python")
    _parse_coverage_json(cov_file, result)
    assert result.coverage_percent is None


def test_run_qlty_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    result = GradeResult(project="p", template="python")
    _run_qlty(tmp_path, result)
    assert result.qlty_issues == 0
    assert result.qlty_smells == 0
    assert any("qlty not installed" in e for e in result.errors)


def test_count_json_array():
    assert _count_json_array("[]") == 0
    assert _count_json_array('[{"id": 1}, {"id": 2}]') == 2
    assert _count_json_array("not json") == 0
    assert _count_json_array('{"not": "list"}') == 0
    assert _count_json_array("") == 0
