import asyncio

from polymarket_mm_bot.bot_controller import BotController
from polymarket_mm_bot.config import Config


async def _never_finishes(config, flag_path, redemption_state_path, dashboard_state_path):
    while not flag_path.exists():
        await asyncio.sleep(0.01)


async def _finishes_immediately(config, flag_path, redemption_state_path, dashboard_state_path):
    return


def test_not_running_before_start(tmp_path):
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=tmp_path / ".stop",
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )
    assert controller.running is False


def test_start_launches_task_and_reports_running(tmp_path):
    (tmp_path / ".env").write_text("POLY_DRY_RUN=true\n")
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=tmp_path / ".stop",
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )

    async def scenario():
        result = controller.start()
        await asyncio.sleep(0.02)
        return result, controller.running

    result, running = asyncio.run(scenario())
    assert result == "started"
    assert running is True


def test_start_twice_is_a_noop_second_time(tmp_path):
    (tmp_path / ".env").write_text("POLY_DRY_RUN=true\n")
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=tmp_path / ".stop",
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )

    async def scenario():
        first = controller.start()
        await asyncio.sleep(0.01)
        second = controller.start()
        return first, second

    first, second = asyncio.run(scenario())
    assert first == "started"
    assert second == "already running"


def test_stop_touches_flag_file_and_task_completes(tmp_path):
    (tmp_path / ".env").write_text("POLY_DRY_RUN=true\n")
    flag_path = tmp_path / ".stop"
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=flag_path,
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )

    async def scenario():
        controller.start()
        await asyncio.sleep(0.01)
        stop_result = controller.stop()
        await asyncio.sleep(0.05)
        return stop_result, controller.running

    stop_result, running_after = asyncio.run(scenario())
    assert stop_result == "stopping"
    assert flag_path.exists()
    assert running_after is False


def test_stop_when_not_running_is_a_noop(tmp_path):
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=tmp_path / ".stop",
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )
    assert controller.stop() == "not running"


def test_start_clears_stale_stop_flag_from_previous_run(tmp_path):
    (tmp_path / ".env").write_text("POLY_DRY_RUN=true\n")
    flag_path = tmp_path / ".stop"
    flag_path.touch()  # leftover from a previous stop
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=flag_path,
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_never_finishes,
    )

    async def scenario():
        controller.start()
        await asyncio.sleep(0.02)
        return controller.running

    running = asyncio.run(scenario())
    assert running is True
    assert not flag_path.exists()


def test_running_becomes_false_after_bot_finishes_on_its_own(tmp_path):
    (tmp_path / ".env").write_text("POLY_DRY_RUN=true\n")
    controller = BotController(
        env_path=tmp_path / ".env",
        flag_path=tmp_path / ".stop",
        redemption_state_path=tmp_path / "redemption.json",
        dashboard_state_path=tmp_path / "state.json",
        run_bot=_finishes_immediately,
    )

    async def scenario():
        controller.start()
        await asyncio.sleep(0.02)
        return controller.running

    running = asyncio.run(scenario())
    assert running is False
