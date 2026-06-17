"""Configuration loading for the Sawa CLI.

Reads ``SAWA_SUPABASE_URL`` / ``SAWA_SUPABASE_KEY`` / ``SAWA_KALSHI_ENV`` from the
environment. As a convenience for the device deployment, missing keys are also
sourced from an env file (default ``~/.sawa/env``, mode 0600) WITHOUT overriding
anything already present in the environment. Secret values are never logged or
echoed -- they are only placed into ``os.environ`` and returned in the Config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# SAWA_KALSHI_ENV -> Kalshi public API base URL.
KALSHI_BASES = {
    "demo": "https://demo-api.kalshi.co/trade-api/v2",
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
}

# Keys we will source from the env file (allowlist; nothing else is read).
# SAWA_MARKET_URL_TEMPLATE is an optional, non-secret template for building a
# tappable Sawa market-page link, e.g. "https://<domain>/market/{id}". When unset,
# Sawa markets simply carry no url (the Sawa web app lives in a separate repo and
# its domain isn't known here).
_ENV_KEYS = (
    "SAWA_SUPABASE_URL",
    "SAWA_SUPABASE_KEY",
    "SAWA_KALSHI_ENV",
    "SAWA_MARKET_URL_TEMPLATE",
)

DEFAULT_ENV_PATH = "~/.sawa/env"


class ConfigError(Exception):
    """Raised when a required configuration value is missing or invalid (exit 4)."""


@dataclass
class Config:
    supabase_url: str
    supabase_key: str
    kalshi_base: str
    market_url_template: str = ""


def _load_env_file(path):
    """Populate os.environ from a KEY=VALUE file for allowlisted keys only.

    Never overrides an already-set environment variable; never logs values.
    Silently does nothing if the file is absent or unreadable.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _ENV_KEYS and key not in os.environ:
            os.environ[key] = value.strip()


def get_config(env_path=DEFAULT_ENV_PATH):
    """Build a Config from the environment (and optional env file).

    ``env_path=None`` skips the env-file step entirely (used by tests so they
    stay hermetic and never touch real secrets).
    Raises ConfigError if SAWA_KALSHI_ENV is set to something other than
    demo/prod. Supabase values may be empty here; call ``require_supabase`` at
    the point of use to enforce them only for the Supabase code paths.
    """
    if env_path:
        _load_env_file(os.path.expanduser(env_path))
    kalshi_env = (os.environ.get("SAWA_KALSHI_ENV") or "demo").strip().lower()
    if kalshi_env not in KALSHI_BASES:
        raise ConfigError(
            "SAWA_KALSHI_ENV must be 'demo' or 'prod' (got %r)" % kalshi_env
        )
    return Config(
        supabase_url=(os.environ.get("SAWA_SUPABASE_URL") or "").strip(),
        supabase_key=(os.environ.get("SAWA_SUPABASE_KEY") or "").strip(),
        kalshi_base=KALSHI_BASES[kalshi_env],
        market_url_template=(os.environ.get("SAWA_MARKET_URL_TEMPLATE") or "").strip(),
    )


def require_supabase(cfg):
    """Raise ConfigError (exit 4) unless both Supabase URL and key are present."""
    missing = []
    if not cfg.supabase_url:
        missing.append("SAWA_SUPABASE_URL")
    if not cfg.supabase_key:
        missing.append("SAWA_SUPABASE_KEY")
    if missing:
        raise ConfigError("missing required config: %s" % ", ".join(missing))
