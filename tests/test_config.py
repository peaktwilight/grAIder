from pathlib import Path

import pytest

from graider.config import (
    DEFAULT_GITLAB_URL,
    require_token,
    resolve_config,
    token_creation_url,
)
from graider.errors import AuthError


def _missing(tmp_path: Path) -> Path:
    return tmp_path / "nope.toml"


def test_token_from_arg(tmp_path):
    cfg = resolve_config(token="glpat-x", gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.token == "glpat-x"


def test_token_from_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('token = "glpat-file"\n')
    cfg = resolve_config(token=None, gitlab_url=None, config_path=f)
    assert cfg.token == "glpat-file"


def test_arg_beats_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('token = "glpat-file"\n')
    cfg = resolve_config(token="glpat-arg", gitlab_url=None, config_path=f)
    assert cfg.token == "glpat-arg"


def test_no_token_is_none(tmp_path):
    cfg = resolve_config(token=None, gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.token is None


def test_gitlab_url_default(tmp_path):
    cfg = resolve_config(token=None, gitlab_url=None, config_path=_missing(tmp_path))
    assert cfg.gitlab_url == DEFAULT_GITLAB_URL


def test_gitlab_url_from_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('gitlab_url = "https://git.uni.edu"\n')
    cfg = resolve_config(token=None, gitlab_url=None, config_path=f)
    assert cfg.gitlab_url == "https://git.uni.edu"


def test_gitlab_url_arg_beats_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('gitlab_url = "https://git.uni.edu"\n')
    cfg = resolve_config(token=None, gitlab_url="https://gitlab.com", config_path=f)
    assert cfg.gitlab_url == "https://gitlab.com"


def test_token_url_default():
    assert token_creation_url("https://gitlab.com") == (
        "https://gitlab.com/-/user_settings/personal_access_tokens"
    )


def test_token_url_self_hosted_strips_slash():
    assert token_creation_url("https://git.uni.edu/") == (
        "https://git.uni.edu/-/user_settings/personal_access_tokens"
    )


def test_require_token_ok(tmp_path):
    cfg = resolve_config(token="glpat-x", gitlab_url=None, config_path=_missing(tmp_path))
    assert require_token(cfg) == "glpat-x"


def test_require_token_raises_with_url(tmp_path):
    cfg = resolve_config(
        token=None, gitlab_url="https://git.uni.edu", config_path=_missing(tmp_path)
    )
    with pytest.raises(AuthError) as excinfo:
        require_token(cfg)
    assert "https://git.uni.edu/-/user_settings/personal_access_tokens" in str(excinfo.value)


def test_find_project_file_in_parent(tmp_path):
    from graider.config import find_project_file

    (tmp_path / "graider.toml").write_text('org = "swe/2026"\n')
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_project_file(sub) == tmp_path / "graider.toml"


def test_project_file_supplies_gitlab_url(tmp_path):
    (tmp_path / "graider.toml").write_text('gitlab_url = "https://git.uni.edu"\norg = "swe/2026"\n')
    cfg = resolve_config(
        token=None, gitlab_url=None, config_path=_missing(tmp_path), project_start=tmp_path
    )
    assert cfg.gitlab_url == "https://git.uni.edu"
    assert cfg.project is not None
    assert cfg.project.org == "swe/2026"


def test_cli_gitlab_url_beats_project_file(tmp_path):
    (tmp_path / "graider.toml").write_text('gitlab_url = "https://git.uni.edu"\n')
    cfg = resolve_config(
        token=None,
        gitlab_url="https://gitlab.com",
        config_path=_missing(tmp_path),
        project_start=tmp_path,
    )
    assert cfg.gitlab_url == "https://gitlab.com"


def test_project_file_resolve_path(tmp_path):
    from graider.config import load_project_file

    (tmp_path / "graider.toml").write_text('roster = "students.csv"\n')
    pf = load_project_file(tmp_path / "graider.toml")
    assert pf.resolve_path(pf.roster) == tmp_path / "students.csv"
    assert pf.resolve_path("") is None


def test_multi_class_select(tmp_path):
    from graider.config import load_project_file

    (tmp_path / "graider.toml").write_text(
        'default_class = "swe25"\n\n'
        '[class.swe25]\norg = "swe/2026"\nroster = "swe25/students.csv"\n\n'
        '[class.dbs25]\norg = "dbs/2026"\n'
    )
    pf = load_project_file(tmp_path / "graider.toml")
    assert pf.select("swe25").org == "swe/2026"
    assert pf.select("dbs25").org == "dbs/2026"
    assert pf.select(None).org == "swe/2026"  # default_class


def test_multi_class_ambiguous_raises(tmp_path):
    from graider.config import ConfigError, load_project_file

    (tmp_path / "graider.toml").write_text('[class.a]\norg = "a/x"\n\n[class.b]\norg = "b/x"\n')
    pf = load_project_file(tmp_path / "graider.toml")
    with pytest.raises(ConfigError, match="Multiple classes"):
        pf.select(None)


def test_single_class_auto(tmp_path):
    from graider.config import load_project_file

    (tmp_path / "graider.toml").write_text('[class.only]\norg = "o/x"\n')
    pf = load_project_file(tmp_path / "graider.toml")
    assert pf.select(None).org == "o/x"


def test_resolve_config_selects_class(tmp_path):
    (tmp_path / "graider.toml").write_text(
        'default_class = "swe25"\n[class.swe25]\ngitlab_url = "https://git.uni.edu"\n'
    )
    cfg = resolve_config(
        token=None,
        gitlab_url=None,
        config_path=_missing(tmp_path),
        project_start=tmp_path,
        class_name="swe25",
    )
    assert cfg.gitlab_url == "https://git.uni.edu"
