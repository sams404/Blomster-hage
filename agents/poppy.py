"""
Poppy Sales — Аутрич-охотник 🤝🌺
ReAct: Search leads → Qualify → Pitch → Track
"""
import json, re
from .base import BaseAgent, SubAgent
from backend.db import save_lead, get_leads


class PoppySales(BaseAgent):
    name     = "Аутрич-охотник"
    codename = "poppy"
    emoji    = "🤝🌺"

    SEARCH_QUERIES = [
        "norsk frilans innholdsproduksjon e-post",
        "norsk småbedrift trenger markedsføring 2026",
        "AI tools for Norwegian freelancers site:linkedin.com",
        "innholdsskaper Norge kontakt",
    ]

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.add_sub("qualifier", SubAgent("Qualifier", """Оцени потенциального клиента.
JSON:
{"score": 1-10, "fit": "perfect|good|maybe|skip",
 "pain_points": ["..."],
 "best_offer": "росток|сад|полный_сад",
 "reasoning": "1 предложение"}
Только JSON."""))

        self.add_sub("pitcher", SubAgent("Pitcher", """Пишешь холодные письма на норвежском.
Правила: дружелюбно, конкретно, без клише, максимум 5 предложений.
Подпись: Samson | Blomster Hage | blomsterhage.no

Структура:
1. Персональный крючок (что заметил на их сайте/соцсетях)
2. Проблема которую видишь
3. Как Blomster Hage решает её конкретно
4. CTA — ссылка на сайт или вопрос"""))

        self.add_sub("followup", SubAgent("FollowUp", """Пишешь follow-up на норвежском.
3 предложения максимум. Упомяни конкретную выгоду. Заверши вопросом."""))

    def find_and_pitch(self, query: str, max_leads: int = 3) -> int:
        # ReAct: поиск лидов
        search_result = self.react(
            f"Найди потенциальных клиентов используя web_search: '{query}'. "
            "Верни список URL и описаний.",
            system_extra="Ищи норвежские компании и фрилансеров которым нужен AI-контент."
        )

        pitched = 0
        # Парсим URL из результата
        urls = re.findall(r'https?://[^\s\'"<>]+', search_result)[:max_leads]

        for url in urls:
            # Проверить что ещё не питчили
            if get_leads(url=url):
                continue

            # Fetch page
            page = self.tools.call("web_fetch", url=url, max_chars=1500)
            if not page.ok:
                continue

            description = page.data.get("text", "")[:500]

            # Qualify
            qual_raw = self.spawn("qualifier",
                                   f"Оцени клиента {url}:",
                                   context=description)
            try:
                qual = json.loads(qual_raw)
            except Exception:
                continue

            if qual.get("score", 0) < 6 or qual.get("fit") == "skip":
                continue

            # Write pitch
            pitch = self.spawn("pitcher",
                                f"Напиши питч для {url}:",
                                context=f"Сайт: {description}\nБоли: {qual.get('pain_points',[])} Оффер: {qual.get('best_offer','сад')}")

            # Save lead
            save_lead({
                "url":         url,
                "description": description[:300],
                "score":       qual.get("score", 0),
                "fit":         qual.get("fit", ""),
                "pitch":       pitch,
                "status":      "draft",
            })

            # Send if email found
            email = re.search(r"[\w.+-]+@[\w-]+\.\w+", description)
            if email:
                self.tools.call("send_email",
                                 to=email.group(),
                                 subject="En idé til deg 🌱",
                                 body=pitch.replace("\n", "<br>"),
                                 html=True)
                pitched += 1
                self.log("pitched", f"{email.group()} score={qual['score']}")
            else:
                # Сохранить в vault для ручной отправки
                self.tools.call("save_vault",
                                 folder="00-Inbox",
                                 title=f"Lead {url[:40]}",
                                 content=f"URL: {url}\nScore: {qual['score']}\n\n## Pitch\n{pitch}",
                                 tags=["lead", "outreach"],
                                 category="goal")

        return pitched

    def run(self):
        self.log("run", "daily outreach")
        total = 0
        for query in self.SEARCH_QUERIES[:2]:  # 2 запроса/день — антиспам
            total += self.find_and_pitch(query)
        self.log("done", f"pitched {total} leads")
        return total
