"""Telegram bot main entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.api_client import api
from bot.commands import register_bot_commands
from bot.middleware import AllowlistMiddleware
from bot.handlers.board import router as board_router
from bot.handlers.approvals import router as approvals_router
from bot.handlers.control import router as control_router
from bot.handlers.files import router as files_router
from bot.handlers.meta import router as meta_router
from bot.notification_watermarks import (
    advance_watermark,
    build_poll_since,
    extract_event_id,
    get_watermark,
    has_seen_event,
    mark_seen_event,
    set_watermark,
)
from bot.notifications import (
    init_notifications,
    notify_agent_offline,
    notify_approval_pending,
    notify_build_failed,
    notify_pipeline_stage,
    notify_task_unblocked,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_notification_redis: Any | None = None


def create_dispatcher() -> Dispatcher:
    """Create and configure the bot dispatcher."""
    storage = MemoryStorage()

    try:
        from redis.asyncio import Redis
        redis = Redis(host="redis", port=6379, db=1)
        storage = RedisStorage(redis=redis)
        logger.info("Using Redis FSM storage")
    except ImportError:
        logger.info("Using in-memory FSM storage")

    dp = Dispatcher(storage=storage)
    dp.update.middleware(AllowlistMiddleware())

    dp.include_router(board_router)
    dp.include_router(approvals_router)
    dp.include_router(meta_router)
    dp.include_router(control_router)
    dp.include_router(files_router)

    return dp


async def _escalation_seen(key: str) -> bool:
    global _notification_redis
    if _notification_redis is None:
        return False
    return bool(await _notification_redis.sismember("clawdev:notifications:seen", key))


async def _mark_escalation_seen(key: str) -> None:
    global _notification_redis
    if _notification_redis is None:
        return
    await _notification_redis.sadd("clawdev:notifications:seen", key)


async def _init_notification_redis() -> None:
    global _notification_redis
    if _notification_redis is not None:
        return
    try:
        from redis.asyncio import Redis

        _notification_redis = Redis(host="redis", port=6379, db=2)
        await _notification_redis.ping()
        logger.info("Using Redis escalation dedupe store")
    except Exception:
        _notification_redis = None
        logger.info("Using in-memory escalation dedupe semantics")


def _ts_to_iso(ts: float) -> str:
    """Convert a Unix timestamp to ISO 8601 string for API since parameter."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


async def _poll_board_events(
    *,
    board_id: str,
    event_type: str,
    events: list[dict[str, object]],
    notification_redis,
    first_poll: bool,
    send_callback,
) -> float:
    previous_ts = await get_watermark(notification_redis, event_type, destination=board_id)
    if not events:
        return previous_ts
    for event in events:
        event_id = extract_event_id(event_type, event)
        if not event_id:
            continue
        already_seen = await has_seen_event(notification_redis, event_type, board_id, event_id)
        await mark_seen_event(notification_redis, event_type, board_id, event_id)
        if first_poll:
            continue
        if already_seen:
            continue
        await send_callback(event)
    return advance_watermark(previous_ts, event_type, events)


async def notification_poll_loop(stop_event: asyncio.Event) -> None:
    """Poll backend for noteworthy events and push them to Telegram."""
    await _init_notification_redis()
    first_poll = True

    while not stop_event.is_set():
        try:
            boards = await api.list_boards()

            for board in boards:
                board_id = board.get("id", "unknown")
                board_wm = await get_watermark(_notification_redis, "approval", destination=board_id)
                board_since_ts = build_poll_since(board_wm)
                board_since = _ts_to_iso(board_since_ts) if board_since_ts > 0 else None
                board_approvals = await api.list_approvals(board_id, since=board_since)
                next_wm = await _poll_board_events(
                    board_id=board_id,
                    event_type="approval",
                    events=board_approvals,
                    notification_redis=_notification_redis,
                    first_poll=first_poll,
                    send_callback=notify_approval_pending,
                )
                if next_wm > board_wm:
                    await set_watermark(_notification_redis, "approval", next_wm, destination=board_id)

                wm_build = await get_watermark(_notification_redis, "build_failed", destination=board_id)
                since_build_ts = build_poll_since(wm_build)
                since_build = _ts_to_iso(since_build_ts) if since_build_ts > 0 else None
                failed_builds = await api.list_failed_build_runs(since=since_build, board_id=board_id)
                next_wm = await _poll_board_events(
                    board_id=board_id,
                    event_type="build_failed",
                    events=failed_builds,
                    notification_redis=_notification_redis,
                    first_poll=first_poll,
                    send_callback=notify_build_failed,
                )
                if next_wm > wm_build:
                    await set_watermark(_notification_redis, "build_failed", next_wm, destination=board_id)

                wm_run = await get_watermark(_notification_redis, "run_success", destination=board_id)
                since_run_ts = build_poll_since(wm_run)
                since_run = _ts_to_iso(since_run_ts) if since_run_ts > 0 else None
                successful_runs = await api.list_runs_for_notifications(
                    status="succeeded",
                    since=since_run,
                    board_id=board_id,
                )
                next_wm = await _poll_board_events(
                    board_id=board_id,
                    event_type="run_success",
                    events=successful_runs,
                    notification_redis=_notification_redis,
                    first_poll=first_poll,
                    send_callback=notify_pipeline_stage,
                )
                if next_wm > wm_run:
                    await set_watermark(_notification_redis, "run_success", next_wm, destination=board_id)

                wm_unblocked = await get_watermark(_notification_redis, "unblocked", destination=board_id)
                since_unblocked_ts = build_poll_since(wm_unblocked)
                since_unblocked = _ts_to_iso(since_unblocked_ts) if since_unblocked_ts > 0 else None
                tasks = await api.list_unblocked_tasks(since=since_unblocked, board_id=board_id)
                next_wm = await _poll_board_events(
                    board_id=board_id,
                    event_type="unblocked",
                    events=tasks,
                    notification_redis=_notification_redis,
                    first_poll=first_poll,
                    send_callback=notify_task_unblocked,
                )
                if next_wm > wm_unblocked:
                    await set_watermark(_notification_redis, "unblocked", next_wm, destination=board_id)

            escalations = await api.get_escalations()
            for event in escalations.get("escalations", []):
                key = f"{event.get('type')}:{event.get('agent_id') or event.get('run_id') or event.get('task_id')}"
                if await _escalation_seen(f"escalation:{key}"):
                    continue
                await _mark_escalation_seen(f"escalation:{key}")
                if not first_poll and event.get("type") == "agent_offline":
                    await notify_agent_offline(event)

            first_poll = False
        except Exception as exc:
            logger.warning("Notification poller failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except TimeoutError:
            continue


async def main() -> None:
    """Start the Telegram bot."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher()

    allowed_ids = list(settings.allowed_ids)
    init_notifications(bot, allowed_ids)
    await register_bot_commands(bot)
    stop_event = asyncio.Event()
    notification_task = asyncio.create_task(notification_poll_loop(stop_event))

    logger.info("Starting ClawDev Telegram Bot...")
    logger.info("Allowed users: %s", allowed_ids or "NONE — all blocked!")
    logger.info("API URL: %s", settings.api_base_url)

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Bot stopped")
    finally:
        stop_event.set()
        notification_task.cancel()
        with suppress(Exception):
            await notification_task
        if _notification_redis is not None:
            with suppress(Exception):
                await _notification_redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
