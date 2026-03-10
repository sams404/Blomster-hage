"""
Orchestrator — Главный планировщик всех агентов.
Запускает агентов по расписанию, мониторит результаты.

Расписание:
  08:00 — Rosa (контент)       ежедневно
  08:00, 12:00, 16:00, 20:00 — Helianthus (крипто-сигналы)
  10:00 — Poppy (аутрич)      ежедневно, пн-пт
  09:00 — Fern (автоматизация) по воскресеньям

Запуск: python -m agents.orchestrator
"""
import os, signal, sys, logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("orchestrator")


def run_rosa():
    try:
        from agents.rosa import RosaDamascena
        RosaDamascena().run()
    except Exception as e:
        log.error(f"Rosa failed: {e}")


def run_helianthus():
    try:
        from agents.helianthus import Helianthus
        Helianthus().run()
    except Exception as e:
        log.error(f"Helianthus failed: {e}")


def run_poppy():
    try:
        from agents.poppy import PoppySales
        PoppySales().run()
    except Exception as e:
        log.error(f"Poppy failed: {e}")


def run_fern():
    try:
        from agents.fern import FernProtocol
        FernProtocol().run()
    except Exception as e:
        log.error(f"Fern failed: {e}")


def heartbeat():
    log.info(f"💚 Orchestrator alive | {datetime.utcnow().isoformat()}")


def main():
    from backend.db import init_db
    init_db()
    log.info("🌺 Blomster Hage Orchestrator starting...")

    scheduler = BlockingScheduler(timezone="Europe/Oslo")

    # Rosa — контент каждый день в 08:00
    scheduler.add_job(run_rosa, CronTrigger(hour=8, minute=0),
                      id="rosa", name="Rosa Damascena")

    # Helianthus — крипто каждые 4 часа
    scheduler.add_job(run_helianthus, CronTrigger(hour="8,12,16,20", minute=0),
                      id="helianthus", name="Helianthus")

    # Poppy — аутрич пн-пт в 10:00
    scheduler.add_job(run_poppy, CronTrigger(day_of_week="mon-fri", hour=10, minute=0),
                      id="poppy", name="Poppy Sales")

    # Fern — воскресенье в 09:00 (оптимизация систем)
    scheduler.add_job(run_fern, CronTrigger(day_of_week="sun", hour=9, minute=0),
                      id="fern", name="Fern Protocol")

    # Heartbeat каждые 30 минут
    scheduler.add_job(heartbeat, CronTrigger(minute="*/30"),
                      id="heartbeat", name="Heartbeat")

    def handle_exit(sig, frame):
        log.info("Shutting down orchestrator...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT,  handle_exit)

    log.info("✅ Scheduler started. Agents running 24/7.")
    log.info("Jobs:")
    for job in scheduler.get_jobs():
        log.info(f"  {job.name}: {job.trigger}")

    scheduler.start()


if __name__ == "__main__":
    main()
