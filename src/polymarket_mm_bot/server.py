from __future__ import annotations

import argparse
import logging
from pathlib import Path

from aiohttp import web

from polymarket_mm_bot.bot_controller import BotController
from polymarket_mm_bot.env_writer import ENV_KEYS, masked_config_status, write_env_updates

logger = logging.getLogger("polymarket_mm_bot.server")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD_DIR = REPO_ROOT / "dashboard"
INDEX_HTML = DASHBOARD_DIR / "index.html"


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(INDEX_HTML)


async def handle_get_config(request: web.Request) -> web.Response:
    controller: BotController = request.app["controller"]
    status = masked_config_status(controller.env_path)
    status["running"] = controller.running
    return web.json_response(status)


async def handle_post_config(request: web.Request) -> web.Response:
    controller: BotController = request.app["controller"]
    body = await request.json()
    if not isinstance(body, dict):
        return web.json_response({"error": "expected a JSON object"}, status=400)
    updates = {key: str(value) for key, value in body.items() if key in ENV_KEYS}
    write_env_updates(controller.env_path, updates)
    return web.json_response({"status": "saved"})


async def handle_post_start(request: web.Request) -> web.Response:
    controller: BotController = request.app["controller"]
    try:
        result = controller.start()
    except ValueError as exc:
        # Config.from_env raises this when a required credential is missing
        # and POLY_DRY_RUN=false - surface it to the form instead of a 500.
        return web.json_response({"status": "error", "message": str(exc)}, status=400)
    return web.json_response({"status": result, "running": controller.running})


async def handle_post_stop(request: web.Request) -> web.Response:
    controller: BotController = request.app["controller"]
    result = controller.stop()
    return web.json_response({"status": result})


async def handle_get_state(request: web.Request) -> web.Response:
    controller: BotController = request.app["controller"]
    if controller.dashboard_state_path.exists():
        return web.Response(text=controller.dashboard_state_path.read_text(), content_type="application/json")
    return web.json_response({"generated_at": None, "running": controller.running})


def build_app(
    env_path: Path,
    flag_path: Path,
    redemption_state_path: Path,
    dashboard_state_path: Path,
) -> web.Application:
    app = web.Application()
    app["controller"] = BotController(env_path, flag_path, redemption_state_path, dashboard_state_path)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/config", handle_get_config)
    app.router.add_post("/api/config", handle_post_config)
    app.router.add_post("/api/start", handle_post_start)
    app.router.add_post("/api/stop", handle_post_stop)
    app.router.add_get("/api/state", handle_get_state)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--flag-file", type=Path, default=Path(".stop"))
    parser.add_argument("--redemption-state-file", type=Path, default=Path(".redemption_queue.json"))
    parser.add_argument("--dashboard-state-file", type=Path, default=DASHBOARD_DIR / "state.json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    app = build_app(args.env_file, args.flag_file, args.redemption_state_file, args.dashboard_state_file)

    # Localhost only, always. This server can write your Polymarket API
    # secret and wallet private key to disk and hold them in .env - it must
    # never be reachable from anything other than this machine's browser.
    logger.info("dashboard at http://127.0.0.1:%d (localhost only)", args.port)
    web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
