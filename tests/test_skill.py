import pathlib

SKILL = pathlib.Path(__file__).resolve().parent.parent / "skills" / "sawa" / "SKILL.md"


def _text():
    return SKILL.read_text(encoding="utf-8")


def test_skill_file_exists():
    assert SKILL.is_file()


def test_frontmatter_name_and_all_triggers():
    text = _text()
    assert text.startswith("---")
    assert "name: sawa" in text
    for trigger in ("/markets", "/search", "/show", "/create", "/suggest", "@bokchoy", "Sawa"):
        assert trigger in text, "missing trigger %r" % trigger


def test_uses_sawa_bin_placeholder_and_json():
    text = _text()
    assert "__SAWA_BIN__" in text
    assert "--json" in text


def test_one_fewshot_invocation_per_command():
    text = _text()
    for command in ("markets", "show", "create", "suggest"):
        assert "__SAWA_BIN__ %s" % command in text, "no few-shot for %r" % command


def test_create_explicitly_creates_nothing():
    text = _text().lower()
    assert "nothing was created" in text
    assert "stub" in text or "preview only" in text


def test_virtual_framing_and_no_pii_rule():
    text = _text().lower()
    assert "sawa coins" in text
    assert "no cash value" in text
    assert "pii" in text
    assert "read-only" in text
