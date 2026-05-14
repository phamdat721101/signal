"""Standalone scheduler process — runs background jobs without blocking API."""
import logging
import time
import signal
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    from app.scheduler import start_scheduler, stop_scheduler

    def shutdown(sig, frame):
        stop_scheduler()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info("Scheduler worker starting...")
    start_scheduler()
    logger.info("Scheduler running. Ctrl+C to stop.")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
