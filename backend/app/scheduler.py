import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import get_settings

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    global _scheduler
    settings = get_settings()
    _scheduler = BackgroundScheduler()

    from app.signal_engine import run_signal_cycle

    _scheduler.add_job(
        run_signal_cycle,
        "interval",
        minutes=settings.signal_interval_minutes,
        id="signal_cycle",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler started — signal cycle every {settings.signal_interval_minutes}m")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        logger.info("Scheduler stopped")
        _scheduler = None
