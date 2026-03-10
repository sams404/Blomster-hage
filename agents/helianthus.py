"""
Helianthus — Крипто-трейдер 📊🌻
ReAct: Fetch prices → Analyze → Write signal → Send to subscribers
"""
import json, os
from .base import BaseAgent, SubAgent

COINS = ["bitcoin", "ethereum", "solana", "cardano"]


class Helianthus(BaseAgent):
    name     = "Крипто-трейдер"
    codename = "helianthus"
    emoji    = "📊🌻"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.add_sub("analyst", SubAgent("TechnicalAnalyst", """Ты технический аналитик.
Анализируй рыночные данные. Формат JSON:
{"trend": "bullish|bearish|neutral",
 "recommendation": "buy|sell|hold",
 "entry_price": number,
 "stop_loss": number,
 "take_profit": number,
 "confidence": 1-10,
 "reasoning": "2-3 предложения"}
Только JSON."""))

        self.add_sub("signal_writer", SubAgent("SignalWriter", """Ты пишешь чёткие сигналы.
Формат (2 версии — RU и NO):
🟢/🔴/🟡 [COIN] — [ДЕЙСТВИЕ]
💰 Вход: $X | 🛑 SL: $X | 🎯 TP: $X
📊 Уверенность: X/10
💡 [Объяснение 1 строка]

---
🟢/🔴/🟡 [COIN] — [HANDLING]
💰 Inngang: $X | 🛑 SL: $X | 🎯 TP: $X
📊 Tillit: X/10"""))

    def analyze_coin(self, coin_id: str) -> dict | None:
        # 1. ReAct: получить данные
        price_result = self.tools.call("crypto_price", coin_id=coin_id)
        if not price_result.ok:
            self.log("skip", f"{coin_id}: {price_result.error}")
            return None

        data = price_result.data
        data_str = json.dumps(data, ensure_ascii=False)

        # 2. Analyst sub-agent
        analysis_raw = self.spawn("analyst",
                                   f"Проанализируй {data['name']}:",
                                   context=data_str)
        try:
            analysis = json.loads(analysis_raw)
        except Exception:
            return None

        rec = analysis.get("recommendation", "hold")
        if rec == "hold":
            return None  # не рассылаем hold

        # 3. Signal writer sub-agent
        signal = self.spawn("signal_writer",
                             f"Напиши сигнал для {data['name']}:",
                             context=f"Данные: {data_str}\nАнализ: {analysis_raw}")

        return {"coin": data["coin"], "analysis": analysis, "signal": signal,
                "price": data["price_usd"], "change_24h": data["change_24h"]}

    def run(self):
        self.log("run", f"analyzing {len(COINS)} coins")
        active_signals = []

        for coin in COINS:
            result = self.analyze_coin(coin)
            if not result:
                continue

            active_signals.append(result)
            self.save_result("signal", json.dumps(result, ensure_ascii=False))
            self.log("signal", f"{result['coin']} → {result['analysis']['recommendation'].upper()}")

            # Сохранить в vault
            self.tools.call("save_vault",
                             folder="05-Knowledge",
                             title=f"Signal {result['coin']} {result['analysis']['recommendation'].upper()}",
                             content=result["signal"],
                             tags=["crypto", "signal", result["coin"].lower()],
                             category="knowledge")

        # Разослать подписчикам
        if active_signals:
            signal_text = "\n\n---\n\n".join(s["signal"] for s in active_signals)
            subscribers = self.tools.call("read_db",
                                           query="SELECT * FROM subscribers WHERE active=1 AND agents LIKE '%helianthus%'")
            if subscribers.ok:
                for sub in subscribers.data:
                    self.tools.call("send_email",
                                     to=sub["email"],
                                     subject=f"📊 Крипто-сигнал | {', '.join(s['coin'] for s in active_signals)}",
                                     body=f"""
<div style="font-family:monospace;background:#080808;color:#e6e2d8;padding:40px;">
  <p style="color:#c9a96e;font-size:11px;">📊🌻 HELIANTHUS SIGNAL</p>
  <div style="white-space:pre-wrap;line-height:2;">{signal_text}</div>
  <p style="font-size:10px;color:rgba(230,226,216,0.3);margin-top:24px;">
    Не является финансовым советом. DYOR.</p>
</div>""")

            # Telegram (если настроен)
            tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
            if tg_chat:
                self.tools.call("telegram_send",
                                 chat_id=tg_chat,
                                 message=f"📊 *Новые сигналы Blomster Hage*\n\n{signal_text[:3000]}")

        self.log("done", f"{len(active_signals)} active signals")
        return active_signals
