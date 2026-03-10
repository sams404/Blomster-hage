"""
Helianthus — Крипто-трейдер (Agent 02)
Автоматически анализирует рынок и рассылает сигналы подписчикам.

Pipeline:
  DataAgent → AnalystAgent → SentimentAgent → SignalAgent → PublishAgent

Доход: kr 99/мес за Telegram-канал с сигналами
"""
import json, requests
from .base import BaseAgent, SubAgent
from backend.email import send_signal


COINS_TO_TRACK = ["bitcoin", "ethereum", "solana", "cardano", "polkadot"]


class Helianthus(BaseAgent):
    name     = "Крипто-трейдер"
    codename = "helianthus"
    emoji    = "📊🌻"

    def __init__(self):
        super().__init__()
        self._setup_sub_agents()

    def _setup_sub_agents(self):
        self.register_sub_agent("analyst", SubAgent(
            name="TechnicalAnalyst",
            system_prompt="""Ты технический аналитик крипторынка.
Анализируй данные цен и объёмов.
Формат ответа JSON:
{"trend": "bullish|bearish|neutral", "strength": 1-10,
 "support": price, "resistance": price,
 "recommendation": "buy|sell|hold",
 "reasoning": "2-3 предложения",
 "confidence": 1-10}
Только JSON, без markdown."""
        ))

        self.register_sub_agent("sentiment", SubAgent(
            name="SentimentAgent",
            system_prompt="""Ты анализируешь настроения крипторынка.
На основе данных о цене и объёмах определи настроение рынка.
Формат JSON:
{"fear_greed_index": 0-100, "market_mood": "extreme_fear|fear|neutral|greed|extreme_greed",
 "key_factors": ["factor1", "factor2"], "short_term_outlook": "..."}
Только JSON."""
        ))

        self.register_sub_agent("signal_writer", SubAgent(
            name="SignalWriter",
            system_prompt="""Ты пишешь чёткие торговые сигналы для подписчиков.
Язык: русский + норвежский (2 версии).
Формат: эмодзи + монета + сигнал + цена входа + стоп-лосс + тейк-профит + объяснение (1 строка).
Пример: 🟢 BTC/USDT — ПОКУПКА | Вход: $42,000 | SL: $40,500 | TP: $46,000 | Пробой уровня сопротивления."""
        ))

    def _fetch_price_data(self, coin_id: str) -> dict:
        """Получает данные о цене с CoinGecko (бесплатно)."""
        try:
            url = (f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                   f"?localization=false&tickers=false&market_data=true"
                   f"&community_data=false&developer_data=false")
            r = requests.get(url, timeout=10)
            d = r.json()
            md = d.get("market_data", {})
            return {
                "coin":           d["symbol"].upper(),
                "name":           d["name"],
                "price_usd":      md.get("current_price", {}).get("usd", 0),
                "change_24h":     md.get("price_change_percentage_24h", 0),
                "change_7d":      md.get("price_change_percentage_7d", 0),
                "volume_24h":     md.get("total_volume", {}).get("usd", 0),
                "market_cap":     md.get("market_cap", {}).get("usd", 0),
                "ath":            md.get("ath", {}).get("usd", 0),
                "ath_change_pct": md.get("ath_change_percentage", {}).get("usd", 0),
            }
        except Exception as e:
            self.log("fetch_error", str(e))
            return {}

    def analyze_coin(self, coin_id: str) -> dict:
        """Полный анализ одной монеты через цепочку суб-агентов."""
        data = self._fetch_price_data(coin_id)
        if not data:
            return {}

        data_str = json.dumps(data, ensure_ascii=False)

        # Sub-agent 1: Technical analysis
        analysis_raw = self.spawn("analyst",
                                   f"Проанализируй данные для {data['name']}:",
                                   context=data_str)
        try:
            analysis = json.loads(analysis_raw)
        except Exception:
            analysis = {"recommendation": "hold", "reasoning": analysis_raw}

        # Sub-agent 2: Sentiment
        sentiment_raw = self.spawn("sentiment",
                                    f"Оцени настроение рынка для {data['name']}:",
                                    context=data_str)
        try:
            sentiment = json.loads(sentiment_raw)
        except Exception:
            sentiment = {"market_mood": "neutral"}

        # Sub-agent 3: Write signal
        signal_text = self.spawn(
            "signal_writer",
            f"Напиши торговый сигнал для {data['name']}:",
            context=f"Данные: {data_str}\nАнализ: {analysis_raw}\nНастроение: {sentiment_raw}"
        )

        result = {
            "coin":       data["coin"],
            "price":      data["price_usd"],
            "change_24h": data["change_24h"],
            "analysis":   analysis,
            "sentiment":  sentiment,
            "signal":     signal_text,
        }
        return result

    def run(self):
        """Запускается каждые 4 часа. Анализирует монеты и рассылает сигналы."""
        self.log("run", f"analyzing {len(COINS_TO_TRACK)} coins")
        signals = []

        for coin in COINS_TO_TRACK:
            result = self.analyze_coin(coin)
            if not result:
                continue

            # Сохранить только если есть buy/sell сигнал (не hold)
            rec = result.get("analysis", {}).get("recommendation", "hold")
            if rec in ("buy", "sell"):
                signals.append(result)
                self.save_result("signal", json.dumps(result, ensure_ascii=False))
                self.log("signal", f"{result['coin']} → {rec.upper()}")

        # Разослать сигналы подписчикам (план "Сад" и выше)
        if signals:
            subscribers = self.get_subscribers()
            crypto_subs = [s for s in subscribers if "helianthus" in s.get("agents", "")]
            for sub in crypto_subs:
                signal_text = "\n\n".join(s["signal"] for s in signals)
                send_signal(sub["email"], signal_text)

        self.log("done", f"{len(signals)} active signals sent")
        return signals
