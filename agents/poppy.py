"""
Poppy Sales — Аутрич-охотник (Agent 04)
Находит потенциальных клиентов, пишет питчи, отправляет письма.
Работает полностью автоматически 24/7.

Pipeline:
  LeadFinderAgent → QualifierAgent → PitchWriterAgent → FollowUpAgent

Доход: каждый привлечённый клиент = kr 149-699/мес recurring
"""
import json, requests
from .base import BaseAgent, SubAgent
from backend.email import send_outreach
from backend.db import get_leads, save_lead, mark_lead_contacted


NORWAY_KEYWORDS = [
    "norsk småbedrift AI",
    "norsk frilans automatisering",
    "AI verktøy Norge 2026",
    "innhold markedsføring Oslo",
    "digital markedsføring Bergen",
]


class PoppySales(BaseAgent):
    name     = "Аутрич-охотник"
    codename = "poppy"
    emoji    = "🤝🌺"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.register_sub_agent("qualifier", SubAgent(
            name="LeadQualifier",
            system_prompt="""Ты квалификатор лидов.
Оцени потенциального клиента по описанию.
Формат JSON:
{"score": 1-10, "fit": "perfect|good|maybe|skip",
 "pain_points": ["point1", "point2"],
 "budget_estimate_nok": 0,
 "reasoning": "1 предложение"}
Только JSON."""
        ))

        self.register_sub_agent("pitcher", SubAgent(
            name="PitchWriter",
            system_prompt="""Ты эксперт по холодным письмам (cold email) в Норвегии.
Пиши на норвежском (bokmål). Тон: дружелюбный, профессиональный, конкретный.
Структура: 1 строка зацепка → 1 строка проблема → 2 строки решение → CTA.
Письмо максимум 5 предложений. Без шаблонных фраз типа "Jeg håper...".
Подпись: Samson | Blomster Hage AI | blomster-hage.vercel.app"""
        ))

        self.register_sub_agent("followup", SubAgent(
            name="FollowUpWriter",
            system_prompt="""Ты пишешь follow-up письма через 3 дня после первого контакта.
Норвежский язык. Максимум 3 предложения.
Упомяни конкретную пользу, которую получит клиент.
Закончи вопросом, требующим короткого ответа."""
        ))

    def _find_leads_duckduckgo(self, keyword: str) -> list[dict]:
        """Ищет потенциальных клиентов через DuckDuckGo API (бесплатно)."""
        try:
            url = "https://api.duckduckgo.com/"
            params = {
                "q":    keyword,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            }
            r = requests.get(url, params=params, timeout=10)
            data = r.json()

            leads = []
            for item in data.get("RelatedTopics", [])[:10]:
                if isinstance(item, dict) and item.get("FirstURL"):
                    leads.append({
                        "url":         item["FirstURL"],
                        "description": item.get("Text", "")[:200],
                        "source":      keyword,
                    })
            return leads
        except Exception as e:
            self.log("lead_search_error", str(e))
            return []

    def qualify_and_pitch(self, lead: dict) -> bool:
        """Квалифицирует лида и отправляет питч если score >= 6."""
        # Sub-agent 1: Qualify
        qual_raw = self.spawn(
            "qualifier",
            f"Оцени этого потенциального клиента:",
            context=f"URL: {lead['url']}\nОписание: {lead['description']}"
        )
        try:
            qual = json.loads(qual_raw)
        except Exception:
            return False

        score = qual.get("score", 0)
        fit   = qual.get("fit", "skip")

        if score < 6 or fit == "skip":
            self.log("skip_lead", f"score={score} {lead['url'][:50]}")
            return False

        # Sub-agent 2: Write pitch
        pitch = self.spawn(
            "pitcher",
            f"Напиши холодное письмо для этого клиента:",
            context=f"""Клиент: {lead['url']}
Описание: {lead['description']}
Боли: {', '.join(qual.get('pain_points', []))}
Бюджет: kr {qual.get('budget_estimate_nok', 349)}"""
        )

        # Сохрани лида в БД
        lead_id = save_lead({
            "url":         lead["url"],
            "description": lead["description"],
            "score":       score,
            "fit":         fit,
            "pitch":       pitch,
            "status":      "pitched",
        })

        # Отправь письмо (если есть email — вытащи из description или URL)
        email = self._extract_email(lead["description"])
        if email:
            send_outreach(email, pitch)
            mark_lead_contacted(lead_id)
            self.log("pitched", f"{email} score={score}")
            return True

        # Сохрани для ручной отправки
        self.save_result("outreach_draft", json.dumps({
            "lead": lead, "pitch": pitch, "score": score
        }, ensure_ascii=False))
        self.log("draft_saved", f"no email found for {lead['url'][:50]}")
        return False

    def _extract_email(self, text: str) -> str | None:
        import re
        m = re.search(r"[\w.+-]+@[\w-]+\.\w+", text)
        return m.group(0) if m else None

    def run(self):
        """Запускается раз в день. Ищет и питчит новых клиентов."""
        self.log("run", "starting daily outreach")
        total_pitched = 0

        for keyword in NORWAY_KEYWORDS:
            leads = self._find_leads_duckduckgo(keyword)
            self.log("found_leads", f"{len(leads)} for '{keyword}'")

            for lead in leads:
                # Проверить что этого лида ещё не контактировали
                existing = get_leads(url=lead["url"])
                if existing:
                    continue

                if self.qualify_and_pitch(lead):
                    total_pitched += 1

                # Не больше 5 питчей в день (антиспам)
                if total_pitched >= 5:
                    break

            if total_pitched >= 5:
                break

        self.log("done", f"pitched {total_pitched} leads today")
        return total_pitched
