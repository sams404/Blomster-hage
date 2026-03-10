"""
Iris Intelligence — CEO Agent (Agent 06)
Главный оркестратор всей системы.

Iris:
  1. Читает утренний дайджест (новости, крипто, задачи)
  2. Решает какие агенты запустить и с какими задачами
  3. Собирает результаты
  4. Отправляет Samson сводный отчёт
  5. Адаптирует расписание на основе результатов

Это "мозг" системы — остальные агенты выполняют,
Iris — планирует и координирует.
"""
import json
from datetime import datetime
from .base import BaseAgent, SubAgent
from agents.tools import TOOLS
from backend.db import get_stats


MORNING_TASKS = [
    # (агент, задача, приоритет)
    ("helianthus", "Проанализируй BTC, ETH, SOL и дай торговые сигналы", 1),
    ("rosa",       "Создай 1 контент-кусок для Samson на тему AI в Норвегии", 2),
    ("poppy",      "Найди 3 новых потенциальных клиента для Blomster Hage", 3),
]


class IrisIntelligence(BaseAgent):
    name     = "ИИ-аналитик CEO"
    codename = "iris"
    emoji    = "🧠🔮"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.add_sub("planner", SubAgent(
            name="Planner",
            system="""Ты стратег AI-системы.
На основе статистики и контекста реши какие задачи нужно выполнить сегодня.
Формат JSON:
{"priority_tasks": [{"agent": "...", "task": "...", "why": "..."}],
 "skip_today": [{"agent": "...", "reason": "..."}],
 "focus_message": "1 предложение о главном фокусе дня"}
Только JSON."""
        ))

        self.add_sub("summarizer", SubAgent(
            name="Summarizer",
            system="""Ты пишешь краткие сводки для занятого человека.
Язык: русский. Максимум 200 слов.
Формат:
## 🌅 Доброе утро, Samson!
### 📊 Главные метрики
### 🎯 Сегодня агенты сделают
### 💰 Прогноз дохода недели
### ⚡ Требует твоего внимания (если есть)"""
        ))

    def morning_brief(self) -> str:
        """Генерирует утренний дайджест для Samson."""
        self.log("morning_brief", datetime.now().strftime("%Y-%m-%d %H:%M"))

        # Получить статистику системы
        stats = get_stats()

        # Поиск актуальных новостей
        news_result = self.tools.call("web_search",
                                       query="AI automation Norway freelance 2026",
                                       max_results=3)
        news = str(news_result)

        # Крипто-данные
        btc = self.tools.call("crypto_price", coin_id="bitcoin")
        eth = self.tools.call("crypto_price", coin_id="ethereum")

        btc_data = btc.data or {}
        eth_data = eth.data or {}
        context = f"""
Статистика системы:
{json.dumps(stats, ensure_ascii=False)}

BTC: ${btc_data.get('price_usd', 0):,.0f} ({btc_data.get('change_24h', 0):+.1f}%)
ETH: ${eth_data.get('price_usd', 0):,.0f} ({eth_data.get('change_24h', 0):+.1f}%)

Свежие новости:
{news[:1000]}

Дата: {datetime.now().strftime('%A, %d %B %Y')}
"""

        # Плановый суб-агент — что делать сегодня
        plan_raw = self.spawn("planner",
                               "Составь план работы агентов на сегодня:",
                               context=context)

        # Суб-агент-резюме — красивый отчёт Samson
        brief = self.spawn("summarizer",
                            "Напиши утренний дайджест для Samson:",
                            context=f"{context}\n\nПлан дня:\n{plan_raw}")

        # Сохранить в vault
        self.tools.call("save_vault",
                         folder="06-Reviews",
                         title=f"Morning Brief {datetime.now().strftime('%Y-%m-%d')}",
                         content=brief,
                         tags=["daily", "iris", "brief"],
                         category="review")

        # Отправить Samson на email
        import os
        owner_email = os.environ.get("OWNER_EMAIL", "")
        if owner_email:
            self.tools.call("send_email",
                             to=owner_email,
                             subject=f"🌅 Blomster Hage — {datetime.now().strftime('%d.%m')}",
                             body=f"""
<div style="font-family:monospace;background:#080808;color:#e6e2d8;padding:40px;max-width:680px;">
  <p style="color:#c9a96e;font-size:11px;letter-spacing:0.2em;">🧠 IRIS · BLOMSTER HAGE</p>
  <div style="white-space:pre-wrap;line-height:1.8;">{brief}</div>
</div>""")

        self.save_result("morning_brief", brief)
        self.log("done", "morning brief sent")
        return brief

    def run(self):
        """Запускается каждое утро в 07:00."""
        return self.morning_brief()

    def run_all_agents(self):
        """Запускает всех агентов по приоритету (для ручного теста)."""
        from agents.rosa import RosaDamascena
        from agents.helianthus import Helianthus
        from agents.poppy import PoppySales

        results = {}
        for agent_class, name in [
            (Helianthus,     "helianthus"),
            (RosaDamascena,  "rosa"),
            (PoppySales,     "poppy"),
        ]:
            self.log(f"delegating", name)
            try:
                a = agent_class()
                results[name] = a.run()
            except Exception as e:
                results[name] = f"ERROR: {e}"
                self.log("error", f"{name}: {e}")

        return results
