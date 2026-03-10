"""
Tool Registry — централизованные инструменты для всех агентов.

Каждый агент получает доступ к tools через self.tools.call(name, **kwargs)

Инструменты:
  web_search   — DuckDuckGo поиск (бесплатно)
  web_fetch    — Загрузить и очистить страницу
  crypto_price — CoinGecko (бесплатно)
  save_vault   — Сохранить заметку в Obsidian vault
  send_email   — Resend API
  save_db      — Сохранить в SQLite
  read_db      — Прочитать из SQLite
"""
import os, re, json, requests, sqlite3
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path.home() / "vault"))
DB_PATH    = Path(__file__).parent.parent / "data" / "blomster.db"
RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "agents@blomsterhage.no")


class ToolResult:
    def __init__(self, ok: bool, data=None, error: str = ""):
        self.ok    = ok
        self.data  = data
        self.error = error

    def __str__(self):
        return json.dumps(self.data, ensure_ascii=False)[:2000] if self.ok else f"ERROR: {self.error}"


class ToolRegistry:

    def call(self, name: str, **kwargs) -> ToolResult:
        fn = getattr(self, f"_tool_{name}", None)
        if fn is None:
            return ToolResult(False, error=f"Unknown tool: {name}")
        try:
            return fn(**kwargs)
        except Exception as e:
            return ToolResult(False, error=str(e))

    def list_tools(self) -> list[str]:
        return [k[6:] for k in dir(self) if k.startswith("_tool_")]

    # ── WEB SEARCH ───────────────────────────────────────────
    def _tool_web_search(self, query: str, max_results: int = 5) -> ToolResult:
        """DuckDuckGo instant answers + HTML search."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; BlomsterBot/1.0)"}
            # DDG HTML
            r = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
                timeout=12,
            )
            soup = BeautifulSoup(r.text, "lxml")
            results = []
            for a in soup.select(".result__a")[:max_results]:
                href = a.get("href", "")
                title = a.get_text(strip=True)
                # extract snippet
                parent = a.find_parent(class_="result")
                snippet = ""
                if parent:
                    snip_el = parent.select_one(".result__snippet")
                    snippet = snip_el.get_text(strip=True) if snip_el else ""
                results.append({"title": title, "url": href, "snippet": snippet})
            return ToolResult(True, {"query": query, "results": results})
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── WEB FETCH ────────────────────────────────────────────
    def _tool_web_fetch(self, url: str, max_chars: int = 4000) -> ToolResult:
        """Загрузить страницу и вернуть чистый текст."""
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "lxml")
            # Remove scripts/styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text()).strip()
            return ToolResult(True, {"url": url, "text": text[:max_chars]})
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── CRYPTO PRICE ─────────────────────────────────────────
    def _tool_crypto_price(self, coin_id: str) -> ToolResult:
        """CoinGecko бесплатное API."""
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                "?localization=false&tickers=false&market_data=true"
                "&community_data=false&developer_data=false",
                timeout=12,
            )
            d  = r.json()
            md = d.get("market_data", {})
            return ToolResult(True, {
                "coin":       d["symbol"].upper(),
                "name":       d["name"],
                "price_usd":  md.get("current_price", {}).get("usd", 0),
                "change_24h": md.get("price_change_percentage_24h", 0),
                "change_7d":  md.get("price_change_percentage_7d", 0),
                "volume_24h": md.get("total_volume", {}).get("usd", 0),
                "ath":        md.get("ath", {}).get("usd", 0),
            })
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── SAVE VAULT (Obsidian) ────────────────────────────────
    def _tool_save_vault(self, folder: str, title: str, content: str,
                          tags: list = None, category: str = "knowledge") -> ToolResult:
        """Сохранить заметку в Obsidian vault с frontmatter."""
        try:
            VAULT_PATH.mkdir(parents=True, exist_ok=True)
            folder_path = VAULT_PATH / folder
            folder_path.mkdir(exist_ok=True)

            slug = re.sub(r"[^\w\s-]", "", title.lower())
            slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:50]
            date = datetime.now().strftime("%Y-%m-%d")
            filename = f"{date}-{slug}.md"

            tags_str = ", ".join(tags or [category, "blomster-hage"])
            note = f"""---
title: {title}
date: {date}
category: {category}
tags: [{tags_str}]
agent: auto
---
{content}
"""
            (folder_path / filename).write_text(note, encoding="utf-8")
            return ToolResult(True, {"path": str(folder_path / filename), "file": filename})
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── SEND EMAIL ───────────────────────────────────────────
    def _tool_send_email(self, to: str, subject: str, body: str,
                          html: bool = True) -> ToolResult:
        """Resend API."""
        if not RESEND_KEY:
            return ToolResult(False, error="RESEND_API_KEY not set")
        try:
            payload = {
                "from":    FROM_EMAIL,
                "to":      to,
                "subject": subject,
            }
            if html:
                payload["html"] = body
            else:
                payload["text"] = body

            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_KEY}",
                         "Content-Type": "application/json"},
                json=payload, timeout=15,
            )
            return ToolResult(r.status_code in (200, 201),
                              data={"id": r.json().get("id")},
                              error="" if r.ok else r.text[:200])
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── SAVE DB ──────────────────────────────────────────────
    def _tool_save_db(self, table: str, data: dict) -> ToolResult:
        """Сохранить запись в SQLite."""
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cols = ", ".join(data.keys())
            vals = tuple(data.values())
            placeholders = ", ".join("?" * len(data))
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", vals)
            conn.commit()
            conn.close()
            return ToolResult(True, data)
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── READ DB ──────────────────────────────────────────────
    def _tool_read_db(self, query: str, params: tuple = ()) -> ToolResult:
        """Прочитать из SQLite."""
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return ToolResult(True, [dict(r) for r in rows])
        except Exception as e:
            return ToolResult(False, error=str(e))

    # ── TELEGRAM ─────────────────────────────────────────────
    def _tool_telegram_send(self, chat_id: str, message: str) -> ToolResult:
        """Отправить сообщение в Telegram."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return ToolResult(False, error="TELEGRAM_BOT_TOKEN not set")
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message,
                      "parse_mode": "Markdown"},
                timeout=10,
            )
            return ToolResult(r.ok, r.json())
        except Exception as e:
            return ToolResult(False, error=str(e))


# Singleton
TOOLS = ToolRegistry()
