"""Telegram bot main entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.api_client import api
from bot.middleware import AllowlistMiddleware
from bot.handlers.board import router as board_router
from bot.handlers.approvals import router as approvals_router
from bot.handlers.control import router as control_router
from bot.handlers.files import router as files_router
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

_notification_redis = None


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
    dp.include_router(control_router)
    dp.include_router(files_router)

    return dp


async def _notification_seen(key: str) -> bool:
    global _notification_redis
    if _notification_redis is None:
        return False
    return bool(await _notification_redis.sismember("clawdev:notifications:seen", key))


async def _mark_notification_seen(key: str) -> None:
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
        logger.info("Using Redis notification dedupe store")
    except Exception:
        _notification_redis = None
        logger.info("Using in-memory notification dedupe semantics")


async def _get_notification_watermark(key: str) -> float:
    """Get a notification watermark timestamp from Redis."""
    global _notification_redis
    if _notification_redis is None:
        return 0.0
    val = await _notification_redis.get(f"clawdev:watermark:{key}")
    return float(val) if val else 0.0


async def _set_notification_watermark(key: str, ts: float) -> None:
    """Set a notification watermark timestamp in Redis."""
    global _notification_redis
    if _notification_redis is None:
        return
    await _notification_redis.set(f"clawdev:watermark:{key}", str(ts))


async def notification_poll_loop(stop_event: asyncio.Event) -> None:
    """Poll backend for noteworthy events and push them to Telegram."""
    await _init_notification_redis()
    seen_approvals: set[str] = set()
    seen_failed_runs: set[str] = set()
    seen_escalations: set[str] = set()
    seen_pipeline_runs: set[str] = set()
    seen_unblocked_tasks: set[str] = set()
    first_poll = True
    import time

    while not stop_event.is_set():
        try:
            now_ts = time.time()
            boards = await api.list_boards()
            for board in boards:
                approvals = await api.list_approvals(board.get("id"))
                for approval in approvals:
                    approval_id = str(approval.get("id"))
                    if approval_id and approval_id not in seen_approvals and not await _notification_seen(f"approval:{approval_id}"):
                        seen_approvals.add(approval_id)
                        await _mark_notification_seen(f"approval:{approval_id}")
                        if not first_poll:
                            await notify_approval_pending(approval)

            failed_builds = await api.list_failed_build_runs()
            for run in failed_builds:
                run_id = str(run.get("id"))
                if run_id and run_id not in seen_failed_runs and not await _notification_seen(f"build_failed:{run_id}"):
                    seen_failed_runs.add(run_id)
                    await _mark_notification_seen(f"build_failed:{run_id}")
                    if not first_poll:
                        await notify_build_failed(run)

            successful_runs = await api.list_runs_for_notifications(status="succeeded")
            for run in successful_runs:
                run_id = str(run.get("id"))
                if not run_id or run_id in seen_pipeline_runs or await _notification_seen(f"pipeline:{run_id}"):
                    continue
                seen_pipeline_runs.add(run_id)
                await _mark_notification_seen(f"pipeline:{run_id}")
                if not first_poll:
                    await notify_pipeline_stage(run)

            tasks = await api.list_unblocked_tasks()
            for task in tasks:
                task_id = str(task.get("id"))
                if not task_id or task_id in seen_unblocked_tasks or await _notification_seen(f"unblocked:{task_id}"):
                    continue
                seen_unblocked_tasks.add(task_id)
                await _mark_notification_seen(f"unblocked:{task_id}")
                if not first_poll:
                    await notify_task_unblocked(task)

            escalations = await api.get_escalations()
            for event in escalations.get("escalations", []):
                key = f"{event.get('type')}:{event.get('agent_id') or event.get('run_id') or event.get('task_id')}"
                if key in seen_escalations or await _notification_seen(f"escalation:{key}"):
                    continue
                seen_escalations.add(key)
                await _mark_notification_seen(f"escalation:{key}")
                if not first_poll and event.get("type") == "agent_offline":
                    await notify_agent_offline(event)

            # Persist watermarks so restarts don't replay old events.
            if _notification_redis is not None:
                await _set_notification_watermark("last_poll_ts", now_ts)

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
