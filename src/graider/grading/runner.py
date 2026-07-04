"""Run qlty + tests over a repo and normalize into a GradeResult."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from graider.errors import GraiderError
from graider.models import GradeResult
from graider.project_config import load_repo_config


def grade_project(repo_dir: Path) -> GradeResult:
    config = load_repo_config(repo_dir)
    if config is None:
        raise GraiderError(f"No .graider.yml found in {repo_dir}")
    result = GradeResult(project=repo_dir.name, template=config.template)
    _run_qlty(repo_dir, result)
    _run_tests(repo_dir, config.template, result)
    return result


def _capture(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)


def _run_qlty(repo_dir: Path, result: GradeResult) -> None:
    if not shutil.which("qlty"):
        result.errors.append("qlty not installed; skipped issues/smells")
        return
    check = _capture(["qlty", "check", "--no-fail", "--format=json"], repo_dir)
    result.qlty_issues = _count_json_array(check.stdout)
    smells = _capture(["qlty", "smells", "--format=json"], repo_dir)
    result.qlty_smells = _count_json_array(smells.stdout)


def _count_json_array(text: str) -> int:
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return 0
    return len(data) if isinstance(data, list) else 0


def _run_tests(repo_dir: Path, template: str, result: GradeResult) -> None:
    handlers = {"python": _tests_python, "java": _tests_java, "cpp": _tests_cpp}
    handler = handlers.get(template)
    if handler is None:
        result.errors.append(f"no test runner for template {template!r}")
        return
    handler(repo_dir, result)


def _tests_python(repo_dir: Path, result: GradeResult) -> None:
    junit = repo_dir / ".graider-junit.xml"
    cov = repo_dir / ".graider-cov.json"

    # Isolate the inner uv from the outer virtualenv and relative UV_CACHE_DIR
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    if "UV_CACHE_DIR" in env:
        cache_path = Path(env["UV_CACHE_DIR"])
        if not cache_path.is_absolute():
            env["UV_CACHE_DIR"] = str(repo_dir.parent / ".uv-cache")
    else:
        env["UV_CACHE_DIR"] = str(repo_dir.parent / ".uv-cache")

    _capture(
        [
            "uv",
            "run",
            "--with",
            "pytest-cov",
            "pytest",
            f"--junit-xml={junit}",
            "--cov=.",
            f"--cov-report=json:{cov}",
        ],
        repo_dir,
        env=env,
    )
    _parse_junit(junit, result)
    _parse_coverage_json(cov, result)


def _tests_java(repo_dir: Path, result: GradeResult) -> None:
    _capture(["gradle", "test", "--no-daemon"], repo_dir)
    # gradle writes one XML per test class under build/test-results/test/
    reports = sorted((repo_dir / "build" / "test-results" / "test").glob("*.xml"))
    _parse_junit_many(reports, result)


def _tests_cpp(repo_dir: Path, result: GradeResult) -> None:
    junit = repo_dir / ".graider-junit.xml"
    _capture(["cmake", "-B", "build"], repo_dir)
    _capture(["cmake", "--build", "build"], repo_dir)
    _capture(["ctest", "--test-dir", "build", f"--output-junit={junit}"], repo_dir)
    _parse_junit(junit, result)


def _parse_junit(path: Path, result: GradeResult) -> None:
    if not path.exists():
        result.errors.append("no test results produced")
        return
    _parse_junit_many([path], result)


def _parse_junit_many(paths: list[Path], result: GradeResult) -> None:
    if not paths:
        result.errors.append("no test results produced")
        return
    total = failed = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
        for suite in suites:
            total += int(suite.get("tests", "0"))
            failed += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
    result.tests_passed = total - failed
    result.tests_failed = failed


def _parse_coverage_json(path: Path, result: GradeResult) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result.coverage_percent = round(data["totals"]["percent_covered"], 1)
    except (json.JSONDecodeError, KeyError, OSError):
        pass
