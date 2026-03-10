"""
Fern Protocol — Автоматизатор (Agent 03)
Раз в неделю оптимизирует работу всей системы:
- Анализирует результаты других агентов
- Создаёт отчёт для Samson
- Предлагает улучшения
- Очищает старые данные
"""
import json
from datetime import datetime, timedelta
from .base import BaseAgent, SubAgent
from backend.email import send_content_delivery
from backend.db import get_stats


class FernProtocol(BaseAgent):
    name     = "Автоматизатор"
    codename = "fern"
    emoji    = "⚙️🌿"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.register_sub_agent("analyst", SubAgent(
            name="SystemAnalyst",
            system_prompt="""Ты аналитик AI-системы. Анализируй статистику и давай рекомендации.
Формат JSON:
{"health_score": 1-10, "top_issues": [], "quick_wins": [],
 "revenue_forecast_nok": 0, "recommended_actions": []}
Только JSON."""
        ))

        self.register_sub_agent("report_writer", SubAgent(
            name="ReportWriter",
            system_prompt="""Ты пишешь еженедельные отчёты для владельца AI-платформы.
Язык: русский. Тон: деловой, конкретный.
Структура:
## Неделя {N} — Отчёт Blomster Hage
### 📊 Ключевые метрики
### 🏆 Что сработало
### ⚠️ Что нужно улучшить
### 🎯 Приоритеты следующей недели
### 💰 Прогноз дохода"""
        ))

    def run(self):
        """Воскресный анализ и отчёт."""
        self.log("run", "weekly system analysis")

        stats = get_stats()

        # Sub-agent 1: Analyze system health
        analysis_raw = self.spawn(
            "analyst",
            "Проанализируй работу системы за неделю:",
            context=json.dumps(stats, ensure_ascii=False)
        )

        # Sub-agent 2: Write weekly report
        week_num = datetime.now().isocalendar()[1]
        report = self.spawn(
            "report_writer",
            f"Напиши отчёт за неделю {week_num}:",
            context=f"Статистика:\n{json.dumps(stats, ensure_ascii=False)}\n\nАнализ:\n{analysis_raw}"
        )

        self.save_result("weekly_report", report)

        # Отправить отчёт Samson
        send_content_delivery(
            to_email=None,
            subject=f"📊 Blomster Hage — Отчёт недели {week_num}",
            content=report,
            agent_name=self.name,
        )

        # Очистка старых логов (старше 30 дней)
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        self.db.execute("DELETE FROM agent_logs WHERE ts < ?", (cutoff,))
        self.db.commit()

        self.log("done", f"week {week_num} report sent")
