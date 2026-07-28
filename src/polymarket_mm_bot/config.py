from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    funder_address: str
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    polygon_rpc_url: str = "https://polygon-rpc.com"
    capital_per_window_usd: float = 100.0
    max_concurrent_windows: int = 1
    n_ladder_levels: int = 4
    imbalance_ceiling_shares: float = 200.0
    pull_quote_seconds_before_close: float = 8.0
    dry_run: bool = True

    @staticmethod
    def from_env(env_path: Path | None = None) -> "Config":
        load_dotenv(dotenv_path=env_path)

        def _get(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        def _get_required_unless_dry_run(name: str, dry_run: bool) -> str:
            value = os.environ.get(name, "")
            if not dry_run and not value:
                raise ValueError(f"missing required environment variable: {name}")
            return value

        dry_run = _get("POLY_DRY_RUN", "true").lower() != "false"

        return Config(
            private_key=_get_required_unless_dry_run("POLY_PRIVATE_KEY", dry_run),
            api_key=_get_required_unless_dry_run("POLY_API_KEY", dry_run),
            api_secret=_get_required_unless_dry_run("POLY_API_SECRET", dry_run),
            api_passphrase=_get_required_unless_dry_run("POLY_API_PASSPHRASE", dry_run),
            funder_address=_get_required_unless_dry_run("POLY_FUNDER_ADDRESS", dry_run),
            clob_host=_get("POLY_CLOB_HOST", "https://clob.polymarket.com"),
            gamma_host=_get("POLY_GAMMA_HOST", "https://gamma-api.polymarket.com"),
            polygon_rpc_url=_get("POLY_POLYGON_RPC_URL", "https://polygon-rpc.com"),
            capital_per_window_usd=float(_get("POLY_CAPITAL_PER_WINDOW_USD", "100")),
            max_concurrent_windows=int(_get("POLY_MAX_CONCURRENT_WINDOWS", "1")),
            n_ladder_levels=int(_get("POLY_N_LADDER_LEVELS", "4")),
            imbalance_ceiling_shares=float(_get("POLY_IMBALANCE_CEILING_SHARES", "200")),
            pull_quote_seconds_before_close=float(_get("POLY_PULL_QUOTE_SECONDS", "8")),
            dry_run=dry_run,
        )
