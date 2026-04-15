"""Scheduler — runs card generation + signal resolution cycles."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def start_scheduler():
    from app.content_engine import run_card_generation_cycle
    from app.signal_engine import run_signal_cycle, resolve_all_signals

    # Card generation every 5 minutes (primary)
    scheduler.add_job(run_card_generation_cycle, "interval", minutes=5, id="card_gen", max_instances=1)
    # Legacy signal cycle 3x/day
    scheduler.add_job(lambda: run_signal_cycle(), "cron", hour="8,14,20", id="signal_cycle", max_instances=1)
    scheduler.add_job(resolve_all_signals, "cron", hour=23, minute=55, id="resolve_signals", max_instances=1)
    scheduler.start()
    logger.info("Scheduler started: card_gen(5m) + signal_cycle(3x/day) + resolve(23:55)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
