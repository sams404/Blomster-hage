"""
BaseAgent — основа для всех агентов.
Каждый агент может порождать суб-агентов через spawn_sub_agent().
"""
import os, json, sqlite3
from datetime import datetime
from groq import Groq

GROQ_MODEL = "llama-3.3-70b-versatile"
DB_PATH = os.path.join(os.path.dirname(__file__), "../data/blomster.db")

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))


class SubAgent:
    """Лёгкий суб-агент — специализированный помощник с одной задачей."""
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt

    def run(self, task: str, context: str = "") -> str:
        content = f"{context}\n\n{task}" if context else task
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": content},
            ],
            max_tokens=2000,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()


class BaseAgent:
    """Базовый агент. Наследуй и реализуй метод run()."""

    name     = "Base"
    codename = "base"
    emoji    = "🤖"

    def __init__(self):
        self.db = self._get_db()
        self._sub_agents: dict[str, SubAgent] = {}

    # ── DB helpers ─────────────────────────────────────────
    def _get_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def log(self, action: str, detail: str = ""):
        self.db.execute(
            "INSERT INTO agent_logs (agent, action, detail, ts) VALUES (?,?,?,?)",
            (self.codename, action, detail, datetime.utcnow().isoformat()),
        )
        self.db.commit()
        print(f"[{self.emoji} {self.codename}] {action}: {detail[:80]}")

    def save_result(self, result_type: str, content: str, client_id: str = ""):
        self.db.execute(
            "INSERT INTO agent_results (agent, result_type, content, client_id, ts)"
            " VALUES (?,?,?,?,?)",
            (self.codename, result_type, content, client_id,
             datetime.utcnow().isoformat()),
        )
        self.db.commit()

    def get_subscribers(self) -> list:
        rows = self.db.execute(
            "SELECT * FROM subscribers WHERE plan != '' AND active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Sub-agent factory ───────────────────────────────────
    def register_sub_agent(self, key: str, agent: SubAgent):
        self._sub_agents[key] = agent

    def spawn(self, key: str, task: str, context: str = "") -> str:
        """Порождает суб-агента по ключу."""
        if key not in self._sub_agents:
            raise ValueError(f"Sub-agent '{key}' not registered")
        self.log(f"spawn:{key}", task[:60])
        result = self._sub_agents[key].run(task, context)
        return result

    # ── Override ────────────────────────────────────────────
    def run(self):
        raise NotImplementedError
