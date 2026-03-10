"""
Rosa Damascena — Контент-мастер ✍️🌸
ReAct pipeline: Research → Draft → Edit → SEO → Deliver
"""
import json
from .base import BaseAgent, SubAgent


class RosaDamascena(BaseAgent):
    name     = "Контент-мастер"
    codename = "rosa"
    emoji    = "✍️🌸"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.add_sub("drafter", SubAgent("Drafter", """Ты опытный копирайтер.
Пиши контент на тему. Структура: цепляющий заголовок → крючок → 3-4 блока → CTA.
Тон: профессиональный, конкретный, без воды. Не более 600 слов."""))

        self.add_sub("editor", SubAgent("Editor", """Ты редактор.
Улучши текст: убери повторы, усиль аргументы, добавь конкретики.
Верни только улучшенный текст."""))

        self.add_sub("seo", SubAgent("SEO", """Ты SEO-специалист.
Добавь SEO к тексту. Формат JSON:
{"title": "...", "meta_description": "...(max 160 chars)",
 "keywords": ["kw1","kw2","kw3"], "content": "полный текст с SEO"}
Только JSON."""))

        self.add_sub("translator", SubAgent("Translator", """Ты переводчик RU→NO (bokmål).
Переводи профессионально, сохраняй тон. Только перевод."""))

    def create(self, topic: str, lang: str = "ru", client_id: str = "") -> dict:
        self.log("create", f"{topic[:50]} [{lang}]")

        # 1. ReAct: поиск информации по теме
        research = self.react(
            f"Найди актуальную информацию и факты по теме: {topic}. "
            f"Используй web_search. Верни ключевые факты.",
            system_extra=f"Тема контента: {topic}\nЯзык: {lang}"
        )

        # 2. Draft (суб-агент)
        draft = self.spawn("drafter",
                            f"Напиши статью на тему: {topic}",
                            context=f"Факты и данные:\n{research}")

        # 3. Edit (суб-агент)
        edited = self.spawn("editor", "Улучши текст:", context=draft)

        # 4. SEO (суб-агент)
        seo_raw = self.spawn("seo", "Добавь SEO:", context=edited)
        try:
            seo = json.loads(seo_raw)
            content = seo.get("content", edited)
            title   = seo.get("title", topic)
            keywords = seo.get("keywords", [])
        except Exception:
            content, title, keywords = edited, topic, []

        # 5. Translate if needed
        if lang == "no":
            content = self.spawn("translator", content)

        # 6. Save to vault
        self.tools.call("save_vault",
                         folder="05-Knowledge",
                         title=title,
                         content=content,
                         tags=keywords[:3] + ["rosa", lang],
                         category="knowledge")

        # 7. Email to client (or owner)
        import os
        to_email = os.environ.get("OWNER_EMAIL", "")
        if to_email:
            self.tools.call("send_email",
                             to=to_email,
                             subject=f"✍️ {title}",
                             body=f"""
<div style="font-family:monospace;background:#080808;color:#e6e2d8;padding:40px;max-width:680px;">
  <p style="color:#c9a96e;font-size:11px;">✍️🌸 ROSA · BLOMSTER HAGE</p>
  <h1 style="font-size:22px;font-weight:300;">{title}</h1>
  <div style="white-space:pre-wrap;line-height:1.8;color:rgba(230,226,216,0.8);">{content[:2000]}</div>
</div>""")

        result = {"title": title, "content": content, "keywords": keywords, "lang": lang}
        self.save_result("content", json.dumps(result, ensure_ascii=False), client_id)
        self.log("done", title)
        return result

    def run(self):
        topics = [
            ("Hvordan AI-agenter kan øke inntekten din i Norge 2026", "no"),
            ("Aksjesparekonto + AI: автоматический анализ портфеля", "ru"),
        ]
        results = []
        for topic, lang in topics:
            results.append(self.create(topic, lang))
        return results
