import pytest

from sawa import config


def test_kalshi_base_defaults_to_demo(monkeypatch):
    monkeypatch.delenv("SAWA_KALSHI_ENV", raising=False)
    cfg = config.get_config(env_path=None)
    assert cfg.kalshi_base == config.KALSHI_BASES["demo"]


def test_kalshi_env_prod(monkeypatch):
    monkeypatch.setenv("SAWA_KALSHI_ENV", "prod")
    cfg = config.get_config(env_path=None)
    assert cfg.kalshi_base == config.KALSHI_BASES["prod"]


def test_kalshi_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("SAWA_KALSHI_ENV", "staging")
    with pytest.raises(config.ConfigError):
        config.get_config(env_path=None)


def test_require_supabase_raises_when_missing():
    cfg = config.Config(supabase_url="", supabase_key="", kalshi_base="x")
    with pytest.raises(config.ConfigError):
        config.require_supabase(cfg)


def test_require_supabase_ok_when_present():
    cfg = config.Config(supabase_url="https://x", supabase_key="k", kalshi_base="x")
    config.require_supabase(cfg)  # no raise


def test_env_file_fills_missing_without_override(tmp_path, monkeypatch):
    env_file = tmp_path / "env"
    env_file.write_text(
        "SAWA_SUPABASE_URL=https://from-file\nSAWA_SUPABASE_KEY=filekey\n# comment\n"
    )
    monkeypatch.delenv("SAWA_SUPABASE_URL", raising=False)
    monkeypatch.setenv("SAWA_SUPABASE_KEY", "already-set")
    monkeypatch.setenv("SAWA_KALSHI_ENV", "demo")
    cfg = config.get_config(env_path=str(env_file))
    assert cfg.supabase_url == "https://from-file"   # filled from file
    assert cfg.supabase_key == "already-set"          # env wins, not overridden
