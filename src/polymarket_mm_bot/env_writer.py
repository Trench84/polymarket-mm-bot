from __future__ import annotations

import os
from pathlib import Path

# Mirrors Config.from_env's fields (config.py) - kept as an explicit allowlist
# so a POST body can never inject an arbitrary env var into .env.
ENV_KEYS = [
    "POLY_DRY_RUN",
    "POLY_PRIVATE_KEY",
    "POLY_API_KEY",
    "POLY_API_SECRET",
    "POLY_API_PASSPHRASE",
    "POLY_FUNDER_ADDRESS",
    "POLY_CLOB_HOST",
    "POLY_GAMMA_HOST",
    "POLY_POLYGON_RPC_URL",
    "POLY_CAPITAL_PER_WINDOW_USD",
    "POLY_MAX_CONCURRENT_WINDOWS",
    "POLY_N_LADDER_LEVELS",
    "POLY_IMBALANCE_CEILING_SHARES",
    "POLY_PULL_QUOTE_SECONDS",
    "POLY_REDEMPTION_MAX_ATTEMPTS",
]

SECRET_KEYS = {"POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET", "POLY_API_PASSPHRASE"}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env_updates(path: Path, updates: dict[str, str]) -> None:
    """Merges updates into the existing .env and writes it with owner-only
    permissions (POLY_PRIVATE_KEY and friends live in this file).

    A blank value for a secret key means "leave the existing value alone" -
    the dashboard form never round-trips a real secret back to the browser,
    so an empty secret field on save must not be treated as "clear it".
    """
    current = read_env_file(path)
    for key, value in updates.items():
        if key not in ENV_KEYS:
            continue
        if value == "" and key in SECRET_KEYS:
            continue
        current[key] = value

    lines = [f"{key}={current[key]}" for key in ENV_KEYS if key in current]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def masked_config_status(path: Path) -> dict:
    """What the browser is allowed to know about current config: presence
    flags for secrets, real values for everything else. Never returns a
    secret's actual value, so this is safe to send back over the API."""
    current = read_env_file(path)
    status: dict = {}
    for key in ENV_KEYS:
        if key in SECRET_KEYS:
            status[key] = {"set": bool(current.get(key))}
        else:
            status[key] = current.get(key, "")
    return status
