import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from graider import __version__
from graider.cli import run


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


def test_setup_without_token_shows_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli([*_no_config(tmp_path), "setup"], env={}, monkeypatch=monkeypatch)
    assert result.exit_code == 1
    assert "/-/user_settings/personal_access_tokens" in result.output


def test_setup_with_token_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-x")
    result = run_cli(
        [*_no_config(tmp_path), "setup"], env={"GITLAB_TOKEN": "glpat-x"}, monkeypatch=monkeypatch
    )
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_setup_self_hosted_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    result = run_cli(
        [*_no_config(tmp_path), "--gitlab-url", "https://git.uni.edu", "setup"],
        env={},
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 1
    assert "https://git.uni.edu/-/user_settings/personal_access_tokens" in result.output


def test_malformed_config_file(tmp_path):
    bad_toml = tmp_path / "config.toml"
    bad_toml.write_text("invalid_toml = = =\n")

    result = run_cli(["--config", str(bad_toml), "setup"])
    assert result.exit_code == 1
    assert "Could not read config file" in result.output
