"""
Rosa Damascena — Контент-мастер (Agent 01)
Генерирует контент для клиентов автоматически.

Pipeline:
  ResearchAgent → DraftAgent → EditAgent → SEOAgent → DeliverAgent

Суб-агенты:
  researcher  — собирает данные по теме
  drafter     — пишет черновик
  editor      — полирует стиль и тон
  seo         — добавляет ключевые слова и мета
  translator  — переводит RU → NO/EN по запросу
"""
import json
from .base import BaseAgent, SubAgent
from backend.email import send_content_delivery


PROFILE_SAMSON = """
Клиент: Samson. Живёт в Норвегии.
Специализация: AI-автоматизация, инвестиции (aksjesparekonto), онлайн-бизнес.
Аудитория: норвежцы 25-45, интересующиеся AI и финансами.
Тон: профессиональный, прямой, без воды.
Язык: русский основной, норвежский для публикаций.
"""


class RosaDamascena(BaseAgent):
    name     = "Контент-мастер"
    codename = "rosa"
    emoji    = "✍️🌸"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.register_sub_agent("researcher", SubAgent(
            name="Researcher",
            system_prompt="""Ты исследователь контента.
Задача: собрать ключевые факты, тренды и аргументы по теме.
Формат: JSON с полями:
{"key_facts": [], "trends": [], "target_audience": "", "hook_ideas": []}
Отвечай ТОЛЬКО JSON без markdown."""
        ))

        self.register_sub_agent("drafter", SubAgent(
            name="Drafter",
            system_prompt="""Ты опытный копирайтер.
Задача: написать черновик контента на основе исследования.
Пиши цепляюще, конкретно, без воды.
Структура: заголовок → крючок → 3-5 блоков → CTA."""
        ))

        self.register_sub_agent("editor", SubAgent(
            name="Editor",
            system_prompt="""Ты строгий редактор.
Задача: улучшить текст — убрать воду, усилить аргументы, улучшить ритм.
Сохраняй смысл. Возвращай только улучшенный текст."""
        ))

        self.register_sub_agent("seo", SubAgent(
            name="SEO",
            system_prompt="""Ты SEO-специалист.
Задача: добавить SEO-оптимизацию к тексту.
Формат JSON:
{"title": "...", "meta_description": "...", "keywords": [], "content": "..."}
Отвечай ТОЛЬКО JSON."""
        ))

        self.register_sub_agent("translator", SubAgent(
            name="Translator",
            system_prompt="""Ты профессиональный переводчик RU→NO.
Задача: перевести текст на норвежский (bokmål).
Сохраняй тон и структуру. Возвращай только перевод."""
        ))

    def create_content_piece(self, topic: str, content_type: str = "blog",
                              language: str = "ru", client_id: str = "") -> dict:
        """Полный pipeline создания одного контент-юнита."""
        self.log("start", f"{content_type}: {topic}")

        # Step 1: Research sub-agent
        research_raw = self.spawn("researcher", f"Исследуй тему: {topic}")
        try:
            research = json.loads(research_raw)
        except Exception:
            research = {"key_facts": [research_raw], "trends": [], "hook_ideas": []}

        # Step 2: Draft sub-agent
        draft = self.spawn(
            "drafter",
            f"Напиши {content_type} на тему: {topic}",
            context=f"Профиль клиента:\n{PROFILE_SAMSON}\n\nИсследование:\n{json.dumps(research, ensure_ascii=False)}"
        )

        # Step 3: Edit sub-agent
        polished = self.spawn("editor", "Улучши этот текст:", context=draft)

        # Step 4: SEO sub-agent
        seo_raw = self.spawn("seo", "Добавь SEO:", context=polished)
        try:
            seo = json.loads(seo_raw)
            final_content = seo.get("content", polished)
            title = seo.get("title", topic)
            keywords = seo.get("keywords", [])
        except Exception:
            final_content = polished
            title = topic
            keywords = []

        # Step 5: Translate if needed
        if language == "no":
            final_content = self.spawn("translator", final_content)

        result = {
            "title":    title,
            "content":  final_content,
            "keywords": keywords,
            "type":     content_type,
            "language": language,
            "topic":    topic,
        }

        self.save_result("content", json.dumps(result, ensure_ascii=False), client_id)
        self.log("done", title)
        return result

    def run(self):
        """Запускается по расписанию. Генерирует контент для всех подписчиков."""
        subscribers = self.get_subscribers()
        self.log("run", f"{len(subscribers)} subscribers")

        # Темы недели для Samson (личный аккаунт)
        weekly_topics = [
            ("Aksjesparekonto 2026: топ-5 акций для норвежцев", "blog", "no"),
            ("Как AI-агенты автоматизируют доход: реальные кейсы", "blog", "ru"),
            ("5 AI-инструментов для фрилансера в Норвегии", "blog", "no"),
        ]

        for topic, ctype, lang in weekly_topics:
            piece = self.create_content_piece(topic, ctype, lang, client_id="samson")
            # Отправить на email
            send_content_delivery(
                to_email=None,  # берётся из настроек
                subject=piece["title"],
                content=piece["content"],
                agent_name=self.name,
            )

        # Для платных подписчиков
        for sub in subscribers:
            topics = sub.get("content_topics", "AI, automation, Norway").split(",")
            for topic in topics[:2]:  # 2 темы в неделю на план
                self.create_content_piece(
                    topic.strip(), "blog", "no", client_id=sub["id"]
                )
