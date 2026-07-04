import pytest

from graider.grading.runner import grade_project
from graider.templates import TemplateContext, render_template, write_files

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="uv missing")
def test_grade_python_starter(tmp_path):
    repo = tmp_path / "proj"
    write_files(render_template("python", TemplateContext()), repo)
    result = grade_project(repo)
    assert result.tests_passed >= 1
    assert result.tests_failed == 0
