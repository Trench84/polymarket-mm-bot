import pytest

from polymarket_mm_bot.config import Config


def test_defaults_in_dry_run_mode(monkeypatch, tmp_path):
    for var in [
        "POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
        "POLY_API_PASSPHRASE", "POLY_FUNDER_ADDRESS",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POLY_DRY_RUN", "true")

    config = Config.from_env(env_path=tmp_path / "does-not-exist.env")

    assert config.dry_run is True
    assert config.capital_per_window_usd == 100.0
    assert config.n_ladder_levels == 4
    assert config.clob_host == "https://clob.polymarket.com"


def test_missing_credentials_raise_when_not_dry_run(monkeypatch, tmp_path):
    for var in [
        "POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
        "POLY_API_PASSPHRASE", "POLY_FUNDER_ADDRESS",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POLY_DRY_RUN", "false")

    with pytest.raises(ValueError, match="POLY_PRIVATE_KEY"):
        Config.from_env(env_path=tmp_path / "does-not-exist.env")


def test_reads_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("POLY_DRY_RUN", "true")
    monkeypatch.setenv("POLY_CAPITAL_PER_WINDOW_USD", "250")
    monkeypatch.setenv("POLY_N_LADDER_LEVELS", "6")
    monkeypatch.setenv("POLY_IMBALANCE_CEILING_SHARES", "500")

    config = Config.from_env(env_path=tmp_path / "does-not-exist.env")

    assert config.capital_per_window_usd == 250.0
    assert config.n_ladder_levels == 6
    assert config.imbalance_ceiling_shares == 500.0
