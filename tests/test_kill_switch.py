from polymarket_mm_bot.kill_switch import KillSwitch


def test_not_triggered_when_flag_file_absent(tmp_path):
    switch = KillSwitch(tmp_path / "STOP")
    assert switch.is_triggered() is False


def test_triggered_when_flag_file_present(tmp_path):
    flag_path = tmp_path / "STOP"
    flag_path.write_text("stop")
    switch = KillSwitch(flag_path)
    assert switch.is_triggered() is True
