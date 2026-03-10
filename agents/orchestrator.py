"""
Orchestrator v2 — Планировщик агентов.

Расписание (Oslo time):
  07:00 — Iris    утренний дайджест
  08:00 — Helianthus крипто-сигналы
  10:00 — Poppy   аутрич (пн-пт)
  12:00 — Helianthus
  14:00 — Rosa    контент
  16:00 — Helianthus
  18:00 — Iris    вечерний отчёт
  20:00 — Helianthus
  09:00вс — Fern  еженедельная оптимизация
"""
import sys, signal, logging
from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("orchestrator")


def job(name: str, fn):
    def wrapper():
        log.info(f"▶ {name}")
        try:
            fn()
            log.info(f"✅ {name} done")
        except Exception as e:
            log.error(f"❌ {name} failed: {e}")
    return wrapper


def main():
    from backend.db import init_db
    init_db()
    log.info("🌺 Blomster Hage Orchestrator v2")

    def run_iris_morning():
        from agents.iris import IrisIntelligence
        IrisIntelligence().morning_brief()

    def run_helianthus():
        from agents.helianthus import Helianthus
        Helianthus().run()

    def run_rosa():
        from agents.rosa import RosaDamascena
        RosaDamascena().run()

    def run_poppy():
        from agents.poppy import PoppySales
        PoppySales().run()

    def run_fern():
        from agents.fern import FernProtocol
        FernProtocol().run()

    s = BlockingScheduler(timezone="Europe/Oslo")

    # Iris — утро и вечер
    s.add_job(job("Iris Morning", run_iris_morning),
              CronTrigger(hour=7, minute=0), id="iris_am")

    # Helianthus — каждые 4 часа
    s.add_job(job("Helianthus", run_helianthus),
              CronTrigger(hour="8,12,16,20", minute=0), id="helianthus")

    # Rosa — контент каждый день
    s.add_job(job("Rosa", run_rosa),
              CronTrigger(hour=14, minute=0), id="rosa")

    # Poppy — аутрич пн-пт
    s.add_job(job("Poppy", run_poppy),
              CronTrigger(day_of_week="mon-fri", hour=10, minute=0), id="poppy")

    # Fern — воскресенье
    s.add_job(job("Fern", run_fern),
              CronTrigger(day_of_week="sun", hour=9, minute=0), id="fern")

    def shutdown(sig, frame):
        log.info("Shutting down...")
        s.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT,  shutdown)

    log.info("✅ Running 24/7. Jobs:")
    for j in s.get_jobs():
        log.info(f"  {j.id}: {j.trigger}")

    s.start()


if __name__ == "__main__":
    main()
