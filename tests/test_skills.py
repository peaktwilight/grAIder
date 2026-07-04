from graider.cli import _install_skills


def test_install_skills_copies_skill_md(tmp_path):
    installed = _install_skills(tmp_path)
    assert any(name.endswith("SKILL.md") for name in installed)
    skill = tmp_path / "graider" / "SKILL.md"
    assert skill.exists()
    content = skill.read_text(encoding="utf-8")
    assert content.startswith("---")  # frontmatter
    assert "name: graider" in content
    assert "dry-run" in content.lower()
