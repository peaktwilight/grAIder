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
