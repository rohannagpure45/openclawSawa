from sawa import create_stub


def test_stub_create_creates_nothing():
    result = create_stub.stub_create("Will it rain tomorrow?", ["Yes", "No"], league="weather")
    assert result.created is False
    assert result.stub is True
    assert "Not created" in result.message
    assert result.would_create == {
        "question": "Will it rain tomorrow?",
        "outcomes": ["Yes", "No"],
        "league": "weather",
    }


def test_stub_create_no_league():
    result = create_stub.stub_create("Q?", ["A", "B"])
    assert result.would_create["league"] is None


def test_stub_create_performs_no_io(monkeypatch):
    # If the stub ever reached the network, this would blow up. It must not.
    from sawa import http

    def explode(*a, **k):
        raise AssertionError("stub_create must never perform network I/O")

    monkeypatch.setattr(http, "get_json", explode)
    result = create_stub.stub_create("Q?", ["A", "B"])
    assert result.created is False


def test_create_stub_module_imports_no_io_modules():
    # Source-level guarantee: the stub module pulls in neither http nor config.
    import pathlib

    src = (pathlib.Path(create_stub.__file__)).read_text(encoding="utf-8")
    assert "import http" not in src
    assert "from . import http" not in src
    assert "from . import config" not in src
