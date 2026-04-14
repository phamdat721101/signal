import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler()

    from app.signal_engine import run_signal_cycle, resolve_all_signals

    # 3 signals per day at fixed UTC times: 8am, 2pm, 8pm
    for hour in [8, 14, 20]:
        _scheduler.add_job(
            run_signal_cycle,
            CronTrigger(hour=hour, minute=0, timezone="UTC"),
            id=f"signal_{hour}",
            replace_existing=True,
        )

    # End-of-day resolution at 23:55 UTC
    _scheduler.add_job(
        resolve_all_signals,
        CronTrigger(hour=23, minute=55, timezone="UTC"),
        id="eod_resolve",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started: signals at 08:00/14:00/20:00 UTC, resolve at 23:55 UTC")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        logger.info("Scheduler stopped")
        _scheduler = None
