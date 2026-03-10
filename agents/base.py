"""
BaseAgent v2 — ReAct loop (Reason → Act → Observe → Reflect)

Каждый агент:
1. Получает задачу
2. ДУМАЕТ: что нужно сделать (через LLM)
3. ДЕЙСТВУЕТ: вызывает инструмент
4. НАБЛЮДАЕТ: сохраняет результат
5. ПОВТОРЯЕТ до завершения

Суб-агенты — специализированные помощники с узкой задачей.
"""
import os, json, sqlite3
from datetime import datetime
from groq import Groq
from agents.tools import TOOLS

MODEL    = "llama-3.3-70b-versatile"
MAX_ITER = 6  # максимум шагов на задачу
DB_PATH  = os.path.join(os.path.dirname(__file__), "../data/blomster.db")


def _groq() -> Groq:
    return Groq(api_key=os.environ.get("GROQ_API_KEY", ""))


# ── Sub-agent ─────────────────────────────────────────────────
class SubAgent:
    """Специализированный помощник. Один вызов LLM → результат."""
    def __init__(self, name: str, system: str):
        self.name   = name
        self.system = system

    def run(self, task: str, context: str = "") -> str:
        client = _groq()
        msgs = [{"role": "system", "content": self.system}]
        if context:
            msgs.append({"role": "user", "content": f"Контекст:\n{context}"})
        msgs.append({"role": "user", "content": task})
        resp = client.chat.completions.create(
            model=MODEL, messages=msgs, max_tokens=2000, temperature=0.7
        )
        return resp.choices[0].message.content.strip()


# ── Base Agent ────────────────────────────────────────────────
class BaseAgent:
    name     = "Base"
    codename = "base"
    emoji    = "🤖"

    # Профиль Samson — контекст для всех агентов
    OWNER_PROFILE = """
    Владелец: Samson, Норвегия.
    Интересы: AI-автоматизация, инвестиции (aksjesparekonto, акции), онлайн-доход.
    Язык: русский (личный), норвежский (для клиентов).
    Цель: kr 15 000/мес пассивного дохода через AI-агентов.
    Ценности: автоматизация, дисциплина, маленькие шаги.
    """

    def __init__(self):
        self.tools       = TOOLS
        self.memory      = []          # краткосрочная память текущего запуска
        self._sub_agents: dict[str, SubAgent] = {}
        self._db         = sqlite3.connect(DB_PATH)
        self._db.row_factory = sqlite3.Row

    # ── Logging ───────────────────────────────────────────────
    def log(self, action: str, detail: str = ""):
        msg = f"[{self.emoji} {self.codename}] {action}"
        if detail:
            msg += f": {detail[:100]}"
        print(msg)
        try:
            self._db.execute(
                "INSERT INTO agent_logs (agent,action,detail,ts) VALUES (?,?,?,?)",
                (self.codename, action, detail, datetime.utcnow().isoformat())
            )
            self._db.commit()
        except Exception:
            pass

    def save_result(self, rtype: str, content: str, client_id: str = ""):
        try:
            self._db.execute(
                "INSERT INTO agent_results (agent,result_type,content,client_id,ts)"
                " VALUES (?,?,?,?,?)",
                (self.codename, rtype, content, client_id,
                 datetime.utcnow().isoformat())
            )
            self._db.commit()
        except Exception:
            pass

    # ── Sub-agents ─────────────────────────────────────────────
    def add_sub(self, key: str, agent: SubAgent):
        self._sub_agents[key] = agent

    def spawn(self, key: str, task: str, context: str = "") -> str:
        self.log(f"→{key}", task[:60])
        return self._sub_agents[key].run(task, context)

    # ── ReAct loop ─────────────────────────────────────────────
    def react(self, task: str, system_extra: str = "") -> str:
        """
        Reasoning + Acting loop.
        LLM решает какой инструмент вызвать, вызываем, даём результат обратно.
        """
        client = _groq()
        tool_list = "\n".join(f"  - {t}" for t in self.tools.list_tools())
        system = f"""Ты {self.name} ({self.codename}) — AI-агент платформы Blomster Hage.

Профиль владельца:
{self.OWNER_PROFILE}

{system_extra}

Доступные инструменты:
{tool_list}

Для использования инструмента ответь СТРОГО в формате JSON:
{{"action": "TOOL", "tool": "tool_name", "args": {{"arg": "value"}}}}

Когда задача выполнена, ответь:
{{"action": "DONE", "result": "итоговый результат"}}

Только JSON. Никакого другого текста."""

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": task},
        ]

        for step in range(MAX_ITER):
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, max_tokens=800, temperature=0.3
            )
            raw = resp.choices[0].message.content.strip()

            # Parse JSON
            try:
                m = json.loads(raw)
            except Exception:
                import re
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                m = json.loads(match.group()) if match else {"action": "DONE", "result": raw}

            action = m.get("action", "DONE")

            if action == "DONE":
                result = m.get("result", raw)
                self.memory.append({"step": step, "action": "done", "result": result})
                return result

            if action == "TOOL":
                tool_name = m.get("tool", "")
                tool_args = m.get("args", {})
                self.log(f"tool:{tool_name}", str(tool_args)[:80])

                tool_result = self.tools.call(tool_name, **tool_args)
                obs = str(tool_result)

                self.memory.append({
                    "step": step, "tool": tool_name,
                    "args": tool_args, "result": obs[:500]
                })

                # Добавить результат в историю
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Результат инструмента {tool_name}:\n{obs}"
                })

        return "Превышен лимит шагов"

    # ── Override ───────────────────────────────────────────────
    def run(self):
        raise NotImplementedError
