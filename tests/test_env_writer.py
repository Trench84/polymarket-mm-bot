from polymarket_mm_bot.env_writer import ENV_KEYS, masked_config_status, read_env_file, write_env_updates


def test_read_env_file_missing_returns_empty(tmp_path):
    assert read_env_file(tmp_path / "does-not-exist.env") == {}


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(path, {"POLY_DRY_RUN": "true", "POLY_CAPITAL_PER_WINDOW_USD": "100"})
    values = read_env_file(path)
    assert values["POLY_DRY_RUN"] == "true"
    assert values["POLY_CAPITAL_PER_WINDOW_USD"] == "100"


def test_write_env_updates_ignores_unknown_keys(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(path, {"NOT_A_REAL_KEY": "x", "POLY_DRY_RUN": "true"})
    values = read_env_file(path)
    assert "NOT_A_REAL_KEY" not in values
    assert values["POLY_DRY_RUN"] == "true"


def test_write_env_updates_merges_rather_than_overwrites(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(path, {"POLY_API_KEY": "abc123", "POLY_DRY_RUN": "true"})
    write_env_updates(path, {"POLY_DRY_RUN": "false"})
    values = read_env_file(path)
    assert values["POLY_API_KEY"] == "abc123"
    assert values["POLY_DRY_RUN"] == "false"


def test_write_env_updates_blank_secret_leaves_existing_value_unchanged(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(path, {"POLY_PRIVATE_KEY": "0xsecret"})
    write_env_updates(path, {"POLY_PRIVATE_KEY": ""})
    values = read_env_file(path)
    assert values["POLY_PRIVATE_KEY"] == "0xsecret"


def test_write_env_updates_sets_owner_only_permissions(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(path, {"POLY_PRIVATE_KEY": "0xsecret"})
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_masked_config_status_never_returns_secret_values(tmp_path):
    path = tmp_path / ".env"
    write_env_updates(
        path,
        {
            "POLY_PRIVATE_KEY": "0xsecret",
            "POLY_API_KEY": "key123",
            "POLY_CAPITAL_PER_WINDOW_USD": "100",
        },
    )
    status = masked_config_status(path)
    assert status["POLY_PRIVATE_KEY"] == {"set": True}
    assert status["POLY_API_KEY"] == {"set": True}
    assert status["POLY_CAPITAL_PER_WINDOW_USD"] == "100"
    assert "0xsecret" not in str(status)
    assert "key123" not in str(status)


def test_masked_config_status_reports_unset_secrets(tmp_path):
    status = masked_config_status(tmp_path / "does-not-exist.env")
    assert status["POLY_PRIVATE_KEY"] == {"set": False}


def test_all_env_keys_covered_by_status(tmp_path):
    status = masked_config_status(tmp_path / "does-not-exist.env")
    assert set(status.keys()) == set(ENV_KEYS)
