"""
Crocus Aurum — Финансист 💰🌼
Торгует одновременно на Binance и Revolut X (FIN_BROKERS=binance,revolut).

Цикл (каждый час), для каждой биржи отдельно:
  Портфель → Риск-проверки → Сигналы EMA/RSI по свечам ЭТОЙ биржи → Ордер → Telegram
Отчёт (каждый вечер): общий портфель в NOK + по биржам, P&L, спред
Binance↔Revolut, налог 22% → Email + Telegram

Решения о сделках принимает детерминированная стратегия + риск-менеджер.
LLM только пишет комментарий к отчёту — он не может сам купить/продать.
"""
import os, json, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
from .base import BaseAgent, SubAgent
from .exchanges import get_exchange, active_brokers, broker_mode, ExchangeError

OSLO    = ZoneInfo("Europe/Oslo")
STABLES = {"USDT", "USDC", "USD", "BUSD", "FDUSD"}
NO_TAX  = 0.22  # Norge: gevinst på krypto beskattes som alminnelig inntekt
LABEL   = {"binance": "Binance", "revolut": "Revolut X"}


def _env_f(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


# ── Indicators ────────────────────────────────────────────────
def ema(values: list[float], period: int) -> float:
    k, e = 2 / (period + 1), values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: list[float], period: int = 14) -> float:
    gains, losses = [], []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g, avg_l = sum(gains) / period, sum(losses) / period
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


# ── Agent ─────────────────────────────────────────────────────
class CrocusAurum(BaseAgent):
    name     = "Финансист"
    codename = "crocus"
    emoji    = "💰🌼"

    _nok_rate: float = 0
    _nok_ts:   float = 0

    def __init__(self):
        super().__init__()
        raw = os.environ.get("FIN_ASSETS") or os.environ.get("FIN_SYMBOLS", "BTC,ETH")
        self.assets = [a.strip().upper().removesuffix("USDT") for a in raw.split(",") if a.strip()]
        self.brokers        = active_brokers()
        self.max_pos_pct    = _env_f("FIN_MAX_POSITION_PCT", 25)
        self.max_daily_loss = _env_f("FIN_MAX_DAILY_LOSS_PCT", 5)
        self.stop_loss_pct  = _env_f("FIN_STOP_LOSS_PCT", 4)
        self.max_trades_day = int(_env_f("FIN_MAX_TRADES_PER_DAY", 6))
        self.interval       = os.environ.get("FIN_INTERVAL", "4h")
        self.add_sub("commentator", SubAgent("FinanceCommentator", """Ты личный финансовый
аналитик Samson (Норвегия). Тебе дают JSON с портфелем на Binance и Revolut X и сделками.
Напиши 3-4 коротких предложения на русском: что произошло, риски, что делать дальше.
Без обещаний прибыли. Не выдумывай цифры — только из JSON."""))

    def max_order(self, broker: str) -> float:
        return _env_f(f"FIN_MAX_ORDER_{broker.upper()}", _env_f("FIN_MAX_ORDER_USDT", 50))

    # ── State (kill switch) ───────────────────────────────────
    def get_state(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM finance_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str):
        self._db.execute("INSERT INTO finance_state (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self._db.commit()

    @property
    def halted(self) -> bool:
        return self.get_state("halted", "0") == "1"

    def broker_halted(self, broker: str) -> bool:
        return self.halted or self.get_state(f"halted:{broker}", "0") == "1"

    def halt(self, reason: str, broker: str = ""):
        """Без broker — стоп всей торговли; с broker — только этой биржи."""
        self.set_state(f"halted:{broker}" if broker else "halted", "1")
        self.set_state(f"halt_reason:{broker}" if broker else "halt_reason", reason)
        where = LABEL.get(broker, "везде")
        self.log("HALT", f"{where}: {reason}")
        self.notify(f"🛑 *Crocus остановил торговлю ({where})*\n{reason}\n\n"
                    f"Возобновить: приложение → Финансы → ▶️")

    def resume(self, broker: str = ""):
        """Без broker — снять все стопы; с broker — только стоп этой биржи."""
        for b in ((broker,) if broker else ("", *self.brokers)):
            self.set_state(f"halted:{b}" if b else "halted", "0")
            self.set_state(f"halt_reason:{b}" if b else "halt_reason", "")
        self.log("resume", f"{LABEL.get(broker, 'вся торговля')}: возобновлено вручную")

    # ── Helpers ───────────────────────────────────────────────
    @classmethod
    def usd_nok(cls) -> float:
        if time.time() - cls._nok_ts > 3600 or not cls._nok_rate:
            try:
                r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
                cls._nok_rate, cls._nok_ts = float(r["rates"]["NOK"]), time.time()
            except Exception:
                cls._nok_rate = cls._nok_rate or _env_f("FIN_USD_NOK_FALLBACK", 10.5)
        return cls._nok_rate

    def portfolio(self, ex) -> dict:
        """Балансы биржи → стоимость в USD(T) и NOK. USDT ≈ USD."""
        bals, positions, equity = ex.balances(), {}, 0.0
        for asset, qty in bals.items():
            if asset in STABLES:
                px = 1.0
            else:
                try:
                    px = ex.price(asset)
                except ExchangeError:
                    continue  # пыль/токен без пары — пропускаем
            value = qty * px
            equity += value
            positions[asset] = {"qty": qty, "price": px, "value_usdt": round(value, 2)}
        rate = self.usd_nok()
        return {"equity_usdt": round(equity, 2), "equity_nok": round(equity * rate),
                "usd_nok": rate, "positions": positions,
                "cash_usdt": round(bals.get(ex.cash, 0), 2), "cash": ex.cash}

    def entry_price(self, broker: str, mode: str, symbol: str) -> float:
        """Средняя цена покупок после последней продажи."""
        rows = self._db.execute(
            "SELECT side, qty, price FROM trades WHERE broker=? AND mode=? AND symbol=? "
            "ORDER BY id DESC", (broker, mode, symbol)).fetchall()
        qty = cost = 0.0
        for r in rows:
            if r["side"] == "SELL":
                break
            qty  += r["qty"]
            cost += r["qty"] * r["price"]
        return cost / qty if qty else 0.0

    @staticmethod
    def today_start_utc() -> str:
        start = datetime.now(OSLO).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def trades_today(self, broker: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM trades WHERE ts >= ?", [self.today_start_utc()]
        if broker:
            q += " AND broker=? AND mode=?"
            args += [broker, broker_mode(broker)]
        return [dict(r) for r in self._db.execute(q + " ORDER BY id", args).fetchall()]

    def record_trade(self, broker: str, mode: str, fill: dict, reason: str, pnl):
        self._db.execute(
            "INSERT INTO trades (mode, broker, symbol, side, qty, price, quote_usdt, fee, "
            "pnl_usdt, reason, order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (mode, broker, fill["symbol"], fill["side"], fill["qty"], fill["price"],
             fill["quote"], fill["fee"], pnl, reason, fill["order_id"]))
        self._db.commit()

    def snapshot(self, broker: str, mode: str, pf: dict):
        self._db.execute(
            "INSERT INTO portfolio_snapshots (mode, broker, equity_usdt, equity_nok, positions) "
            "VALUES (?,?,?,?,?)",
            (mode, broker, pf["equity_usdt"], pf["equity_nok"], json.dumps(pf["positions"])))
        self._db.commit()

    def notify(self, text: str):
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if chat:
            self.tools.call("telegram_send", chat_id=chat, message=text[:3900])

    # ── Strategy ──────────────────────────────────────────────
    def signal(self, ex, broker: str, mode: str, asset: str, in_position: bool):
        closes = ex.closes(asset, self.interval, 120)
        if len(closes) < 60:
            return "HOLD", "мало истории свечей", {}
        px = closes[-1]
        fast, slow, r = ema(closes, 20), ema(closes, 50), rsi(closes)
        ind = {"price": px, "ema20": round(fast, 2), "ema50": round(slow, 2), "rsi": round(r, 1)}

        if in_position:
            entry = self.entry_price(broker, mode, ex.pair(asset))
            if entry and px <= entry * (1 - self.stop_loss_pct / 100):
                return "SELL", f"stop-loss −{self.stop_loss_pct}% (вход {entry:.2f})", ind
            if r > 80:
                return "SELL", f"take-profit: RSI {r:.0f} перекуплен", ind
            if fast < slow:
                return "SELL", "тренд развернулся: EMA20 < EMA50", ind
            return "HOLD", "держим позицию", ind

        if fast > slow and px > fast and 45 < r < 70:
            return "BUY", f"восходящий тренд: EMA20 > EMA50, RSI {r:.0f}", ind
        return "HOLD", "нет входа", ind

    # ── Trading cycle ─────────────────────────────────────────
    def run(self) -> dict:
        self.log("run", f"brokers={self.brokers} assets={self.assets}")
        out, total_usdt = {}, 0.0
        for broker in self.brokers:
            try:
                ex = get_exchange(broker)
                out[broker] = self.run_broker(broker, ex)
                total_usdt += out[broker]["portfolio"]["equity_usdt"]
            except ExchangeError as e:
                self.log("error", f"{broker}: {e}")
                out[broker] = {"error": str(e)}
        rate = self.usd_nok()
        self.snapshot("all", "mix", {"equity_usdt": round(total_usdt, 2),
                                     "equity_nok": round(total_usdt * rate), "positions": {}})
        return {"halted": self.halted, "brokers": out,
                "total_nok": round(total_usdt * rate)}

    def run_broker(self, broker: str, ex) -> dict:
        mode = broker_mode(broker)
        pf   = self.portfolio(ex)
        self.snapshot(broker, mode, pf)
        res  = {"mode": mode, "portfolio": pf, "actions": [], "halted": False}

        if self.broker_halted(broker):
            res["halted"] = True
            return res

        # Риск 1: дневной убыток на этой бирже
        first = self._db.execute(
            "SELECT equity_usdt FROM portfolio_snapshots WHERE broker=? AND mode=? AND ts >= ? "
            "ORDER BY id LIMIT 1", (broker, mode, self.today_start_utc())).fetchone()
        if first and first["equity_usdt"] > 0:
            dd = (first["equity_usdt"] - pf["equity_usdt"]) / first["equity_usdt"] * 100
            if dd >= self.max_daily_loss:
                self.halt(f"Дневной убыток {dd:.1f}% ≥ лимита {self.max_daily_loss}%", broker)
                res["halted"] = True
                return res

        for asset in self.assets:
            # Риск 2: лимит сделок в день на биржу
            if len(self.trades_today(broker)) >= self.max_trades_day:
                self.log("limit", f"{broker}: лимит сделок на сегодня")
                break
            pos    = pf["positions"].get(asset, {"qty": 0, "value_usdt": 0})
            in_pos = pos["value_usdt"] >= 10
            try:
                action, reason, ind = self.signal(ex, broker, mode, asset, in_pos)
            except ExchangeError as e:
                self.log("error", f"{broker} {asset}: {e}")
                continue

            pnl = None
            if action == "BUY":
                room = pf["equity_usdt"] * self.max_pos_pct / 100 - pos["value_usdt"]
                size = min(self.max_order(broker), room, pf["cash_usdt"] * 0.98)
                if size < 10:
                    self.log("skip", f"{broker} {asset}: размер {size:.2f} < 10")
                    continue
                fill = self._execute(broker, ex.market_buy, asset, size)
            elif action == "SELL":
                entry = self.entry_price(broker, mode, ex.pair(asset))
                fill  = self._execute(broker, ex.market_sell, asset, pos["qty"])
                if fill and entry:
                    pnl = (fill["price"] - entry) * fill["qty"] - fill["fee"]
            else:
                continue

            if not fill:
                continue
            self.record_trade(broker, mode, fill, reason, pnl)
            pf["cash_usdt"] += -fill["quote"] if action == "BUY" else fill["quote"]
            res["actions"].append({**fill, "reason": reason, "pnl_usdt": pnl, **ind})
            pnl_txt = f"\nP&L: {pnl:+.2f} {ex.cash}" if pnl is not None else ""
            self.notify(f"{'🟢' if action == 'BUY' else '🔴'} *{action} {fill['symbol']}* "
                        f"· {LABEL[broker]} [{mode}]\n"
                        f"{fill['qty']:.6f} @ {fill['price']:.2f} = {fill['quote']:.2f} {ex.cash}\n"
                        f"Причина: {reason}{pnl_txt}")

        self.log("done", f"{broker}: {len(res['actions'])} сделок, "
                         f"equity {pf['equity_usdt']} {ex.cash}")
        return res

    def _execute(self, broker: str, fn, asset: str, amount: float) -> dict | None:
        try:
            return fn(asset, amount)
        except ExchangeError as e:
            self.log("order-failed", f"{broker} {asset}: {e}")
            self.notify(f"⚠️ {LABEL[broker]}: ордер {asset} не прошёл — {e}")
            return None

    # ── Report ────────────────────────────────────────────────
    def build_report(self) -> dict:
        rate, brokers, prices = self.usd_nok(), {}, {}
        total = 0.0
        for broker in self.brokers:
            mode = broker_mode(broker)
            try:
                ex = get_exchange(broker)
                pf = self.portfolio(ex)
                prices[broker] = {a: ex.price(a) for a in self.assets}
            except ExchangeError as e:
                brokers[broker] = {"mode": mode, "error": str(e)}
                continue
            total += pf["equity_usdt"]
            year = f"{datetime.now(OSLO).year}-01-01"
            realized = self._db.execute(
                "SELECT COALESCE(SUM(pnl_usdt),0) s FROM trades WHERE broker=? AND mode=? AND ts >= ?",
                (broker, mode, year)).fetchone()["s"]
            brokers[broker] = {
                "mode": mode, "portfolio": pf, "realized_ytd_usdt": round(realized, 2),
                "halted": self.broker_halted(broker),
                "halt_reason": self.get_state(f"halt_reason:{broker}") or
                               (self.get_state("halt_reason") if self.halted else ""),
                "trades_today": self.trades_today(broker)}

        # Спред между биржами — если одна дешевле, это видно сразу
        spread = {}
        if len(prices) == 2:
            for a in self.assets:
                b, r = prices["binance"][a], prices["revolut"][a]
                spread[a] = round((r - b) / b * 100, 3)

        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        prev = self._db.execute(
            "SELECT equity_usdt FROM portfolio_snapshots WHERE broker='all' AND ts <= ? "
            "ORDER BY id DESC LIMIT 1", (day_ago,)).fetchone()
        change   = total - prev["equity_usdt"] if prev else None
        realized = sum(b.get("realized_ytd_usdt", 0) for b in brokers.values())
        return {
            "date": datetime.now(OSLO).strftime("%d.%m.%Y"), "usd_nok": rate,
            "halted": self.halted, "brokers": brokers, "spread_pct": spread,
            "total_usdt": round(total, 2), "total_nok": round(total * rate),
            "change_24h_nok": round(change * rate) if change is not None else None,
            "realized_ytd_nok": round(realized * rate),
            "tax_estimate_nok": round(max(realized, 0) * rate * NO_TAX),
        }

    @staticmethod
    def _kr(n) -> str:
        return f"{n:,.0f}".replace(",", " ")

    def report(self) -> dict:
        rep = self.build_report()
        try:
            comment = self.spawn("commentator", "Прокомментируй отчёт:",
                                 context=json.dumps(rep, ensure_ascii=False, default=str))
        except Exception as e:
            comment = f"(комментарий недоступен: {e})"
        rep["comment"] = comment

        L = [f"💰🌼 *Crocus Aurum — отчёт {rep['date']}*"
             + (" · 🛑 ОСТАНОВЛЕН" if rep["halted"] else ""),
             "", f"Всего: *kr {self._kr(rep['total_nok'])}*"]
        if rep["change_24h_nok"] is not None:
            L.append(f"За 24ч: {rep['change_24h_nok']:+,} kr".replace(",", " "))
        for broker, b in rep["brokers"].items():
            L += ["", f"*{LABEL[broker]}* `{b['mode']}`" + (" 🛑" if b.get("halted") else "")]
            if "error" in b:
                L.append(f"  ⚠️ {b['error']}")
                continue
            pf = b["portfolio"]
            L.append(f"  kr {self._kr(pf['equity_nok'])} ({pf['equity_usdt']:.2f} {pf['cash']})")
            for asset, p in pf["positions"].items():
                L.append(f"  • {asset}: {p['qty']:.6g} ≈ {p['value_usdt']:.2f}")
            for t in b["trades_today"]:
                pnl = f" P&L {t['pnl_usdt']:+.2f}" if t["pnl_usdt"] is not None else ""
                L.append(f"  {t['side']} {t['symbol']} @ {t['price']:.2f}{pnl} — {t['reason']}")
        if rep["spread_pct"]:
            L += ["", "Спред Revolut X vs Binance: " +
                  ", ".join(f"{a} {s:+.2f}%" for a, s in rep["spread_pct"].items())]
        L += ["",
              f"Реализовано с 1 янв: {rep['realized_ytd_nok']:+,} kr".replace(",", " "),
              f"Налог 22% (оценка): kr {self._kr(rep['tax_estimate_nok'])}",
              "", f"🧠 {comment}"]
        text = "\n".join(L)

        self.notify(text)
        from backend.email import send_content_delivery
        send_content_delivery(None, f"Финансовый отчёт {rep['date']}",
                              text.replace("*", "").replace("`", ""), "Crocus Aurum 💰🌼")
        self.save_result("finance_report", json.dumps(rep, ensure_ascii=False, default=str))
        self.log("report", f"total {rep['total_nok']} NOK")
        return rep
