import pytest

from graider.errors import TemplateError
from graider.templates import (
    TEMPLATES,
    TemplateContext,
    render_template,
    write_files,
)


def _by_path(language, **kw):
    ctx = TemplateContext(**kw)
    return {f.path: f.content for f in render_template(language, ctx)}


def test_templates_list():
    assert set(TEMPLATES) == {"python", "java", "cpp", "go", "rust", "typescript"}


def test_unknown_template_raises():
    with pytest.raises(TemplateError, match="Unknown template"):
        render_template("haskell", TemplateContext())


@pytest.mark.parametrize("language", TEMPLATES)
def test_every_language_has_core_files(language):
    files = _by_path(language)
    assert ".graider.yml" in files
    assert ".gitignore" in files
    assert ".gitlab-ci.yml" in files
    assert "qlty.toml" in files
    assert "README.md" in files
    assert "REFLECTION.md" in files


@pytest.mark.parametrize("language", TEMPLATES)
def test_no_tmpl_or_dot_prefix_leaks(language):
    for path in _by_path(language):
        assert not path.endswith(".tmpl"), path
        assert "dot_" not in path, path


def test_graider_yml_substitution():
    files = _by_path(
        "python",
        course="swe25",
        criteria_repo="https://gl/swe/crit",
        criteria_path="swe25/",
    )
    yml = files[".graider.yml"]
    assert "course: swe25" in yml
    assert "template: python" in yml
    assert "repo: https://gl/swe/crit" in yml
    assert "path: swe25/" in yml
    assert "{{" not in yml  # every placeholder resolved


def test_write_files(tmp_path):
    rendered = render_template("python", TemplateContext())
    write_files(rendered, tmp_path)
    assert (tmp_path / ".graider.yml").exists()
    assert (tmp_path / "src" / "calc.py").exists()
