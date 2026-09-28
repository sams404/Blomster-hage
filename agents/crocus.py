"""
Crocus Aurum — Финансист 💰🌼
Цикл (каждый час): Портфель → Риск-проверки → Сигналы EMA/RSI → Ордер → Уведомление
Отчёт (каждый вечер): Портфель в NOK, P&L, сделки, налог 22% → Email + Telegram

Решения о сделках принимает детерминированная стратегия + риск-менеджер.
LLM только пишет комментарий к отчёту — он не может сам купить/продать.
"""
import os, json, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
from .base import BaseAgent, SubAgent
from .exchanges import get_exchange, split_symbol, ExchangeError

OSLO     = ZoneInfo("Europe/Oslo")
STABLES  = {"USDT", "USDC", "USD", "BUSD", "FDUSD"}
NO_TAX   = 0.22  # Norge: gevinst på krypto beskattes som alminnelig inntekt


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
        self.symbols        = [s.strip().upper() for s in
                               os.environ.get("FIN_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
        self.max_order      = _env_f("FIN_MAX_ORDER_USDT", 50)
        self.max_pos_pct    = _env_f("FIN_MAX_POSITION_PCT", 25)
        self.max_daily_loss = _env_f("FIN_MAX_DAILY_LOSS_PCT", 5)
        self.stop_loss_pct  = _env_f("FIN_STOP_LOSS_PCT", 4)
        self.max_trades_day = int(_env_f("FIN_MAX_TRADES_PER_DAY", 6))
        self.interval       = os.environ.get("FIN_INTERVAL", "4h")
        self.mode           = os.environ.get("FIN_MODE", "paper").lower()
        self.broker         = os.environ.get("FIN_BROKER", "binance").lower()
        self.add_sub("commentator", SubAgent("FinanceCommentator", """Ты личный финансовый
аналитик Samson (Норвегия). Тебе дают JSON с портфелем и сделками.
Напиши 3-4 коротких предложения на русском: что произошло, риски, что делать дальше.
Без обещаний прибыли. Без эмодзи-спама. Не выдумывай цифры — только из JSON."""))

    # ── State (kill switch и т.п.) ────────────────────────────
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

    def halt(self, reason: str):
        self.set_state("halted", "1")
        self.set_state("halt_reason", reason)
        self.log("HALT", reason)
        self.notify(f"🛑 *Crocus остановил торговлю*\n{reason}\n\nВозобновить: admin → /api/finance/resume")

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
        """Балансы → стоимость в USDT и NOK."""
        bals, positions, equity = ex.balances(), {}, 0.0
        for asset, qty in bals.items():
            if asset in STABLES:
                value = qty
                px = 1.0
            else:
                try:
                    px = ex.price(f"{asset}USDT")
                except ExchangeError:
                    continue  # пыль/неизвестный токен — пропускаем
                value = qty * px
            equity += value
            positions[asset] = {"qty": qty, "price": px, "value_usdt": round(value, 2)}
        rate = self.usd_nok()
        return {"equity_usdt": round(equity, 2), "equity_nok": round(equity * rate, 0),
                "usd_nok": rate, "positions": positions,
                "cash_usdt": round(sum(bals.get(s, 0) for s in STABLES), 2)}

    def entry_price(self, symbol: str) -> float:
        """Средняя цена покупок после последней продажи."""
        rows = self._db.execute(
            "SELECT side, qty, price FROM trades WHERE symbol=? AND mode=? ORDER BY id DESC",
            (symbol, self.mode)).fetchall()
        qty = cost = 0.0
        for r in rows:
            if r["side"] == "SELL":
                break
            qty  += r["qty"]
            cost += r["qty"] * r["price"]
        return cost / qty if qty else 0.0

    def today_start_utc(self) -> str:
        start = datetime.now(OSLO).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def trades_today(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM trades WHERE mode=? AND ts >= ? ORDER BY id",
                                (self.mode, self.today_start_utc())).fetchall()
        return [dict(r) for r in rows]

    def record_trade(self, fill: dict, reason: str, pnl: float | None):
        self._db.execute(
            "INSERT INTO trades (mode, broker, symbol, side, qty, price, quote_usdt, fee, "
            "pnl_usdt, reason, order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.mode, self.broker, fill["symbol"], fill["side"], fill["qty"], fill["price"],
             fill["quote"], fill["fee"], pnl, reason, fill["order_id"]))
        self._db.commit()

    def snapshot(self, pf: dict):
        self._db.execute(
            "INSERT INTO portfolio_snapshots (mode, equity_usdt, equity_nok, positions) "
            "VALUES (?,?,?,?)",
            (self.mode, pf["equity_usdt"], pf["equity_nok"], json.dumps(pf["positions"])))
        self._db.commit()

    def notify(self, text: str):
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if chat:
            self.tools.call("telegram_send", chat_id=chat, message=text[:3900])

    # ── Strategy ──────────────────────────────────────────────
    def signal(self, ex, symbol: str, in_position: bool) -> tuple[str, str, dict]:
        closes = ex.klines(symbol, self.interval, 120)
        px     = closes[-1]
        fast, slow, r = ema(closes, 20), ema(closes, 50), rsi(closes)
        ind = {"price": px, "ema20": round(fast, 2), "ema50": round(slow, 2), "rsi": round(r, 1)}

        if in_position:
            entry = self.entry_price(symbol)
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
        self.log("run", f"mode={self.mode} broker={self.broker} symbols={self.symbols}")
        ex = get_exchange()
        pf = self.portfolio(ex)
        self.snapshot(pf)
        actions = []

        if self.halted:
            self.log("halted", self.get_state("halt_reason"))
            return {"halted": True, "portfolio": pf}

        # Риск 1: дневной убыток
        first = self._db.execute(
            "SELECT equity_usdt FROM portfolio_snapshots WHERE mode=? AND ts >= ? ORDER BY id LIMIT 1",
            (self.mode, self.today_start_utc())).fetchone()
        if first and first["equity_usdt"] > 0:
            dd = (first["equity_usdt"] - pf["equity_usdt"]) / first["equity_usdt"] * 100
            if dd >= self.max_daily_loss:
                self.halt(f"Дневной убыток {dd:.1f}% ≥ лимита {self.max_daily_loss}%")
                return {"halted": True, "portfolio": pf}

        # Риск 2: лимит сделок в день
        if len(self.trades_today()) >= self.max_trades_day:
            self.log("limit", "лимит сделок на сегодня исчерпан")
            return {"halted": False, "portfolio": pf, "actions": []}

        for symbol in self.symbols:
            if len(self.trades_today()) >= self.max_trades_day:
                break
            base, _ = split_symbol(symbol)
            pos     = pf["positions"].get(base, {"qty": 0, "value_usdt": 0})
            in_pos  = pos["value_usdt"] >= 10
            try:
                action, reason, ind = self.signal(ex, symbol, in_pos)
            except ExchangeError as e:
                self.log("error", f"{symbol}: {e}")
                continue

            if action == "BUY":
                room  = pf["equity_usdt"] * self.max_pos_pct / 100 - pos["value_usdt"]
                size  = min(self.max_order, room, pf["cash_usdt"] * 0.98)
                if size < 10:
                    self.log("skip", f"{symbol}: размер {size:.2f} < 10 USDT")
                    continue
                fill, pnl = self._execute(ex.market_buy, symbol, size), None
            elif action == "SELL":
                entry = self.entry_price(symbol)
                fill  = self._execute(ex.market_sell, symbol, pos["qty"])
                pnl   = (fill["price"] - entry) * fill["qty"] - fill["fee"] if (fill and entry) else None
            else:
                continue

            if not fill:
                continue
            self.record_trade(fill, reason, pnl)
            pf["cash_usdt"] += -fill["quote"] if action == "BUY" else fill["quote"]
            actions.append({**fill, "reason": reason, "pnl_usdt": pnl, **ind})
            pnl_txt = f"\nP&L: {pnl:+.2f} USDT" if pnl is not None else ""
            self.notify(f"{'🟢' if action == 'BUY' else '🔴'} *{action} {symbol}* [{self.mode}]\n"
                        f"{fill['qty']:.6f} @ {fill['price']:.2f} = {fill['quote']:.2f} USDT\n"
                        f"Причина: {reason}{pnl_txt}")

        self.log("done", f"{len(actions)} сделок, equity {pf['equity_usdt']} USDT")
        return {"halted": False, "portfolio": pf, "actions": actions}

    def _execute(self, fn, symbol: str, amount: float) -> dict | None:
        try:
            return fn(symbol, amount)
        except ExchangeError as e:
            self.log("order-failed", f"{symbol}: {e}")
            self.notify(f"⚠️ Ордер {symbol} не прошёл: {e}")
            return None

    # ── Report ────────────────────────────────────────────────
    def build_report(self) -> dict:
        ex    = get_exchange()
        pf    = self.portfolio(ex)
        rate  = pf["usd_nok"]
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        prev  = self._db.execute(
            "SELECT equity_usdt FROM portfolio_snapshots WHERE mode=? AND ts <= ? ORDER BY id DESC LIMIT 1",
            (self.mode, day_ago)).fetchone()
        year  = f"{datetime.now(OSLO).year}-01-01"
        realized = self._db.execute(
            "SELECT COALESCE(SUM(pnl_usdt),0) s FROM trades WHERE mode=? AND ts >= ?",
            (self.mode, year)).fetchone()["s"]
        change = pf["equity_usdt"] - prev["equity_usdt"] if prev else None
        return {
            "date": datetime.now(OSLO).strftime("%d.%m.%Y"),
            "mode": self.mode, "broker": self.broker,
            "halted": self.halted, "halt_reason": self.get_state("halt_reason") if self.halted else "",
            "portfolio": pf,
            "change_24h_usdt": round(change, 2) if change is not None else None,
            "change_24h_nok":  round(change * rate) if change is not None else None,
            "trades_today": self.trades_today(),
            "realized_ytd_nok": round(realized * rate),
            "tax_estimate_nok": round(max(realized, 0) * rate * NO_TAX),
        }

    def report(self) -> dict:
        rep = self.build_report()
        try:
            comment = self.spawn("commentator", "Прокомментируй отчёт:",
                                 context=json.dumps(rep, ensure_ascii=False, default=str))
        except Exception as e:
            comment = f"(комментарий недоступен: {e})"
        rep["comment"] = comment
        pf = rep["portfolio"]

        lines = [f"💰🌼 *Crocus Aurum — отчёт {rep['date']}*",
                 f"Режим: `{rep['mode']}` · {rep['broker']}" + (" · 🛑 ОСТАНОВЛЕН" if rep["halted"] else ""),
                 "",
                 f"Портфель: *kr {pf['equity_nok']:,.0f}* ({pf['equity_usdt']:,.2f} USDT)".replace(",", " ")]
        if rep["change_24h_nok"] is not None:
            lines.append(f"За 24ч: {rep['change_24h_nok']:+,} kr".replace(",", " "))
        for asset, p in pf["positions"].items():
            lines.append(f"  • {asset}: {p['qty']:.6g} ≈ {p['value_usdt']:.2f} USDT")
        lines.append("")
        lines.append(f"Сделок сегодня: {len(rep['trades_today'])}")
        for t in rep["trades_today"]:
            pnl = f" P&L {t['pnl_usdt']:+.2f}" if t["pnl_usdt"] is not None else ""
            lines.append(f"  {t['side']} {t['symbol']} @ {t['price']:.2f}{pnl} — {t['reason']}")
        lines += ["",
                  f"Реализовано с 1 янв: {rep['realized_ytd_nok']:+,} kr".replace(",", " "),
                  f"Налог 22% (оценка): kr {rep['tax_estimate_nok']:,}".replace(",", " "),
                  "", f"🧠 {comment}"]
        text = "\n".join(lines)

        self.notify(text)
        from backend.email import send_content_delivery
        send_content_delivery(None, f"Финансовый отчёт {rep['date']}",
                              text.replace("*", "").replace("`", ""), "Crocus Aurum 💰🌼")
        self.save_result("finance_report", json.dumps(rep, ensure_ascii=False, default=str))
        self.log("report", f"equity {pf['equity_nok']} NOK")
        return rep
