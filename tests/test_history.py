from graider.grading.history import _parse_log, analyze_history

SEP = "\x1f"


def _log(*commits):
    # commits: list of (email, day, [(add, rm), ...])
    out = []
    for email, day, files in commits:
        out.append(f"C{SEP}{email}{SEP}{day}")
        for add, rm in files:
            out.append(f"{add}\t{rm}\tsome/file.py")
    return "\n".join(out)


def test_parse_log_aggregates():
    text = _log(
        ("a@x.edu", "2026-01-01", [("10", "0")]),
        ("a@x.edu", "2026-01-01", [("5", "2")]),
        ("b@x.edu", "2026-01-05", [("200", "1")]),
    )
    m = _parse_log(text)
    assert m.commits == 3
    assert m.commit_days == 2
    assert m.span_days == 4
    assert m.authors == {"a@x.edu": 2, "b@x.edu": 1}
    assert m.largest_commit_lines == 201  # 200 + 1


def test_parse_log_handles_binary_dashes():
    # git prints '-' for binary files; those must be ignored, not crash.
    text = f"C{SEP}a@x.edu{SEP}2026-01-01\n-\t-\timg.png\n3\t1\tcode.py"
    m = _parse_log(text)
    assert m.commits == 1
    assert m.largest_commit_lines == 4


def test_analyze_history_no_git(monkeypatch):
    import graider.grading.history as hist

    monkeypatch.setattr(hist.shutil, "which", lambda cmd: None)
    assert analyze_history(__import__("pathlib").Path(".")) is None
