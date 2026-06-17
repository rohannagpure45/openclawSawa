import importlib.util
import json
import os

_HELPER = os.path.join(os.path.dirname(__file__), "..", "scripts", "sawa_recent_messages.py")
_spec = importlib.util.spec_from_file_location("sawa_recent_messages", _HELPER)
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)


def _rec(role, text):
    return json.dumps({"type": "message", "message": {"role": role, "content": [{"type": "text", "text": text}]}})


def test_extract_user_messages_text_only_and_strips_sender():
    lines = [
        _rec("user", "Alice: who wins the world cup?"),
        _rec("assistant", "a bot reply"),
        _rec("user", "lakers tonight?"),
        "not json at all",
        json.dumps({"type": "message", "message": {"role": "toolResult", "content": [{"type": "toolResult", "text": "x"}]}}),
    ]
    out = rm.extract_user_messages(lines, limit=10)
    assert out == ["who wins the world cup?", "lakers tonight?"]


def test_extract_respects_limit():
    lines = [_rec("user", "m%d" % i) for i in range(10)]
    assert rm.extract_user_messages(lines, limit=3) == ["m7", "m8", "m9"]


def test_extract_empty_when_no_user_messages():
    lines = [_rec("assistant", "hi"), _rec("toolResult", "x")]
    assert rm.extract_user_messages(lines, limit=5) == []


def test_resolve_session_id_from_index(tmp_path, monkeypatch):
    sessions = tmp_path / "agents" / "main" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "sessions.json").write_text(
        json.dumps([{"key": "agent:main:telegram:group:-1", "id": "SID123"}])
    )
    monkeypatch.setattr(rm, "_SESSIONS_DIR", str(tmp_path / "agents" / "{agent}" / "sessions"))
    assert rm.resolve_session_id("main", "agent:main:telegram:group:-1") == "SID123"
    assert rm.resolve_session_id("main", "missing") is None


def test_recent_messages_end_to_end(tmp_path, monkeypatch):
    sessions = tmp_path / "agents" / "main" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "sessions.json").write_text(json.dumps([{"key": "agent:main:telegram:group:-9", "id": "S"}]))
    (sessions / "S.jsonl").write_text("\n".join([_rec("user", "Bob: portugal world cup?"), _rec("assistant", "x")]))
    monkeypatch.setattr(rm, "_SESSIONS_DIR", str(tmp_path / "agents" / "{agent}" / "sessions"))
    assert rm.recent_messages("main", "agent:main:telegram:group:-9", 10) == ["portugal world cup?"]
