import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import MagicMock

from graider import __version__
from graider.cli import run
from graider.models import (
    CriterionVerdict,
    InviteResult,
    InviteStatus,
    PerformanceLevel,
    ProjectRef,
    ReviewResult,
)


def _no_config(tmp_path):
    # Point --config at a nonexistent file so no real ~/.config leaks in.
    return ["--config", str(tmp_path / "nope.toml")]


def run_cli(args, env=None, monkeypatch=None):
    if env is not None and monkeypatch is not None:
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    old_argv = sys.argv
    sys.argv = ["graider"] + args

    out = StringIO()
    err = StringIO()
    exit_code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            run()
    except SystemExit as e:
        if e.code is None:
            exit_code = 0
        elif isinstance(e.code, int):
            exit_code = e.code
        else:
            exit_code = 1
    finally:
        sys.argv = old_argv

    class Result:
        def __init__(self, exit_code, stdout, stderr):
            self.exit_code = exit_code
            self.stdout = stdout
            self.stderr = stderr
            self.output = stdout + stderr

    return Result(exit_code, out.getvalue(), err.getvalue())


def test_version():
    result = run_cli(["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_subcommands():
    result = run_cli(["--help"])
    assert result.exit_code == 0
    for name in ("setup", "grade", "review", "report"):
        assert name in result.output


def _roster(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("email,group\na@x.edu,1\nb@x.edu,2\n")
    return str(p)


def test_setup_without_token_shows_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli(
        [*_no_config(tmp_path), "setup", "--roster", _roster(tmp_path), "--org", "swe/2026"],
        env={},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 1
    assert "/-/user_settings/personal_access_tokens" in result.output


def test_setup_with_token_env(tmp_path, monkeypatch):
    _fake_client(monkeypatch)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-x")
    state_path = tmp_path / "graider.lock.json"
    result = run_cli(
        [
            *_no_config(tmp_path),
            "setup",
            "--roster",
            _roster(tmp_path),
            "--org",
            "swe/2026",
            "--state",
            str(state_path),
        ],
        env={"GITLAB_TOKEN": "glpat-x"},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    assert "Projects" in result.output


def test_setup_self_hosted_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    args = [
        *_no_config(tmp_path),
        "--gitlab-url",
        "https://git.uni.edu",
        "setup",
        "--roster",
        _roster(tmp_path),
        "--org",
        "swe/2026",
    ]
    result = run_cli(args, env={}, monkeypatch=monkeypatch)
    assert result.exit_code == 1
    assert "https://git.uni.edu/-/user_settings/personal_access_tokens" in result.output


def test_malformed_config_file(tmp_path):
    bad_toml = tmp_path / "config.toml"
    bad_toml.write_text("invalid_toml = = =\n")

    result = run_cli(["--config", str(bad_toml), "setup", "--roster", _roster(tmp_path)])
    assert result.exit_code == 1
    assert "Could not read config file" in result.output


def test_setup_dry_run_prints_groups(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli([*_no_config(tmp_path), "--dry-run", "setup", "--roster", _roster(tmp_path)])
    assert result.exit_code == 0  # no token needed for dry run
    assert "Setup preview" in result.output
    assert "a@x.edu" in result.output


def test_setup_dry_run_flag_after_subcommand(tmp_path, monkeypatch):
    # --dry-run must work when placed after the subcommand, not just before it.
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli([*_no_config(tmp_path), "setup", "--roster", _roster(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "dry run" in result.output.lower()


def test_setup_bad_roster_reports_row(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    bad = tmp_path / "bad.csv"
    bad.write_text("email,group\nnope,1\n")
    result = run_cli([*_no_config(tmp_path), "--dry-run", "setup", "--roster", str(bad)])
    assert result.exit_code == 1
    assert "row 2" in result.output


def _fake_client(monkeypatch):
    client = MagicMock()
    client.get_namespace_id.return_value = 100
    client.list_group_project_paths.return_value = set()
    client.create_project.side_effect = lambda name, ns: ProjectRef(
        id=abs(hash(name)) % 1000,
        name=name,
        path_with_namespace=f"swe/{name}",
        web_url=f"https://gl/swe/{name}",
    )
    client.invite_member.side_effect = lambda pid, email: InviteResult(
        email=email, status=InviteStatus.INVITED, username=email.split("@")[0]
    )
    monkeypatch.setattr("graider.cli.GitLabClient", lambda *a, **k: client)
    return client


def test_setup_creates_projects_and_state(tmp_path, monkeypatch):
    client = _fake_client(monkeypatch)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\nb@x.edu,1\nc@x.edu,2\n")
    state_path = tmp_path / "graider.lock.json"
    result = run_cli(
        [
            *_no_config(tmp_path),
            "setup",
            "--roster",
            str(roster),
            "--org",
            "swe/2026",
            "--state",
            str(state_path),
        ],
        env={"GITLAB_TOKEN": "glpat-x"},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    assert client.create_project.call_count == 2  # two groups
    assert client.commit_files.call_count == 2
    assert client.invite_member.call_count == 3  # three students
    assert state_path.exists()


def test_setup_is_idempotent(tmp_path, monkeypatch):
    client = _fake_client(monkeypatch)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\n")
    state_path = tmp_path / "graider.lock.json"
    args = [
        *_no_config(tmp_path),
        "setup",
        "--roster",
        str(roster),
        "--org",
        "swe/2026",
        "--state",
        str(state_path),
    ]
    run_cli(args, env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch)
    client.create_project.reset_mock()
    # second run: project already in state -> no new creation
    run_cli(args, env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch)
    client.create_project.assert_not_called()


def test_setup_dry_run_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    roster = tmp_path / "r.csv"
    roster.write_text("email,group\na@x.edu,1\n")
    result = run_cli([*_no_config(tmp_path), "--dry-run", "setup", "--roster", str(roster)])
    assert result.exit_code == 0
    assert "dry run" in result.output.lower()


def test_review_dry_run_lists_scope(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    (tmp_path / "criteria.md").write_text("# Brief\nx\n\n## 1. A\na\n\n## 2. B\nb\n")
    result = run_cli(
        [
            *_no_config(tmp_path),
            "review",
            "--criteria-dir",
            str(tmp_path),
            "--up-to",
            "1",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0
    assert "in scope" in result.output
    assert "not yet evaluated" in result.output


def test_report_single_dir(tmp_path, monkeypatch):
    import json as _json

    (tmp_path / "grade-results.json").write_text(
        _json.dumps(
            [
                {
                    "project": "p",
                    "template": "python",
                    "tests_passed": 1,
                    "tests_failed": 0,
                    "coverage_percent": 90.0,
                    "qlty_issues": 0,
                    "qlty_smells": 0,
                    "errors": [],
                }
            ]
        )
    )
    out_dir = tmp_path / "reports"
    monkeypatch.chdir(tmp_path)
    result = run_cli([*_no_config(tmp_path), "report", "--out-dir", str(out_dir)])
    assert result.exit_code == 0
    assert (out_dir / "p.md").exists()
    assert (out_dir / "summary.csv").exists()


def test_setup_reads_graider_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    (tmp_path / "roster.csv").write_text("email,group\na@x.edu,1\n")
    (tmp_path / "graider.toml").write_text(
        'org = "swe/2026"\ntemplate = "python"\nroster = "roster.csv"\n'
    )
    monkeypatch.chdir(tmp_path)
    # no --roster / --org: both come from graider.toml
    result = run_cli(["--config", str(tmp_path / "nope.toml"), "--dry-run", "setup"])
    assert result.exit_code == 0
    assert "a@x.edu" in result.output


def test_init_scaffolds_toml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_cli([*_no_config(tmp_path), "init", "--org", "swe/2026"])
    assert result.exit_code == 0
    assert (tmp_path / "graider.toml").exists()
    assert 'org = "swe/2026"' in (tmp_path / "graider.toml").read_text()
    # re-run without --force errors
    result2 = run_cli([*_no_config(tmp_path), "init"])
    assert result2.exit_code == 1


def _draft_review(tmp_path, published=False):
    path = tmp_path / "review-results.json"
    result = ReviewResult(
        project="brave-otter",
        head_sha="abc",
        model="m",
        cutoff="2",
        overall_summary="Solid.",
        criteria=[
            CriterionVerdict(
                id="1", title="Tests", level=PerformanceLevel.EMERGING, evidence=[], comment="thin"
            )
        ],
        published=published,
        published_at="2026-07-04T00:00:00+00:00" if published else "",
    )
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_review_publish_posts_and_marks_published(tmp_path, monkeypatch):
    path = _draft_review(tmp_path)
    client = MagicMock()
    monkeypatch.setattr("graider.cli.GitLabClient", lambda *a, **k: client)
    result = run_cli(
        [
            *_no_config(tmp_path),
            "review",
            "publish",
            "--yes",
            "--feedback",
            "issue",
            "--project-id",
            "grp/1",
            "--results",
            str(path),
        ],
        env={"GITLAB_TOKEN": "glpat-x"},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    client.upsert_issue.assert_called_once()
    assert json.loads(path.read_text())["published"] is True


def test_review_publish_skips_when_already_published(tmp_path, monkeypatch):
    path = _draft_review(tmp_path, published=True)
    client = MagicMock()
    monkeypatch.setattr("graider.cli.GitLabClient", lambda *a, **k: client)
    result = run_cli(
        [
            *_no_config(tmp_path),
            "review",
            "publish",
            "--yes",
            "--feedback",
            "issue",
            "--project-id",
            "grp/1",
            "--results",
            str(path),
        ],
        env={"GITLAB_TOKEN": "glpat-x"},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    client.upsert_issue.assert_not_called()
    assert "Already published" in result.output
