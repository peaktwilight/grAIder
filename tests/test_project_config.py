import pytest

from graider.errors import GraiderError
from graider.project_config import load_repo_config


def test_load_repo_config_success(tmp_path):
    yml_content = """
course: swe-2026
template: python
criteria:
  repo: course/criteria
  path: grading/rubric.yml
"""
    (tmp_path / ".graider.yml").write_text(yml_content, encoding="utf-8")
    config = load_repo_config(tmp_path)
    assert config is not None
    assert config.course == "swe-2026"
    assert config.template == "python"
    assert config.criteria_repo == "course/criteria"
    assert config.criteria_path == "grading/rubric.yml"


def test_load_repo_config_missing_file(tmp_path):
    config = load_repo_config(tmp_path)
    assert config is None


def test_load_repo_config_missing_template(tmp_path):
    yml_content = """
course: swe-2026
criteria:
  repo: course/criteria
"""
    (tmp_path / ".graider.yml").write_text(yml_content, encoding="utf-8")
    with pytest.raises(GraiderError, match="missing `template`"):
        load_repo_config(tmp_path)


def test_load_repo_config_invalid_yaml(tmp_path):
    (tmp_path / ".graider.yml").write_text(":", encoding="utf-8")
    with pytest.raises(GraiderError, match="Invalid .graider.yml"):
        load_repo_config(tmp_path)
