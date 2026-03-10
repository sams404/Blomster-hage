"""
Единая точка входа.

Запуск:
  python run.py backend      # только API сервер (порт 8000)
  python run.py orchestrator # только агенты по расписанию
  python run.py all          # всё вместе (production)
  python run.py test <agent> # тест одного агента
"""
import sys, os

os.chdir(os.path.dirname(__file__))


def start_backend():
    from backend.db import init_db
    init_db()
    from backend.app import app
    print("🌐 Backend API: http://localhost:8000")
    app.run(host="0.0.0.0", port=8000, debug=False)


def start_orchestrator():
    from agents.orchestrator import main
    main()


def start_all():
    import threading
    t = threading.Thread(target=start_backend, daemon=True)
    t.start()
    start_orchestrator()


def test_agent(name: str):
    from backend.db import init_db
    init_db()
    print(f"🧪 Testing agent: {name}")
    if name == "rosa":
        from agents.rosa import RosaDamascena
        a = RosaDamascena()
        r = a.create_content_piece("AI-автоматизация для норвежского фриланса", "blog", "ru")
        print("\n📝 Result:", r.get("title"))
        print(r.get("content", "")[:500])
    elif name == "helianthus":
        from agents.helianthus import Helianthus
        a = Helianthus()
        r = a.analyze_coin("bitcoin")
        print("\n📊 Signal:", r.get("signal", "")[:300])
    elif name == "poppy":
        from agents.poppy import PoppySales
        PoppySales().run()
    elif name == "fern":
        from agents.fern import FernProtocol
        FernProtocol().run()
    else:
        print(f"Unknown agent: {name}")
        print("Available: rosa, helianthus, poppy, fern")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "backend":
        start_backend()
    elif cmd == "orchestrator":
        start_orchestrator()
    elif cmd == "all":
        start_all()
    elif cmd == "test":
        agent = sys.argv[2] if len(sys.argv) > 2 else "rosa"
        test_agent(agent)
    else:
        print(__doc__)
