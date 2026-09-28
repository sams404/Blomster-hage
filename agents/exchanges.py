"""
Биржи для Crocus Aurum — единый интерфейс.

  PaperExchange     — симуляция на реальных ценах Binance (по умолчанию, без риска)
  BinanceExchange   — testnet (фейковые деньги) или live (реальные деньги)
  RevolutXExchange  — Revolut X (крипто-биржа Revolut). ЭКСПЕРИМЕНТАЛЬНО.

Все биржи умеют:
  price(symbol) -> float
  klines(symbol, interval, limit) -> list[close]
  balances() -> {asset: qty}
  market_buy(symbol, quote_usdt) -> fill
  market_sell(symbol, base_qty) -> fill

fill = {"symbol", "side", "qty", "price", "quote", "fee", "order_id"}

ВАЖНО: ни одна биржа здесь НЕ умеет выводить средства. API-ключи создавай
только с правами "Read" + "Spot Trading", без "Withdraw".
"""
import os, time, hmac, hashlib, json, math, sqlite3, uuid, base64
from urllib.parse import urlencode
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "blomster.db"

BINANCE_PUBLIC  = "https://api.binance.com"
# Публичное зеркало только для рыночных данных (цены/свечи) — без гео-блоков
MARKET_DATA_URL = os.environ.get("FIN_MARKET_DATA_URL", "https://data-api.binance.vision")
BINANCE_TESTNET = "https://testnet.binance.vision"
PAPER_FEE       = 0.001  # 0.1% — как у Binance spot


class ExchangeError(Exception):
    pass


def split_symbol(symbol: str) -> tuple[str, str]:
    """BTCUSDT -> (BTC, USDT)."""
    for quote in ("USDT", "USDC", "USD", "EUR", "NOK"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)], quote
    raise ExchangeError(f"Unknown quote asset in {symbol}")


# ── Market data (публичные данные Binance, без ключей) ────────
class _BinanceMarketData:
    base = MARKET_DATA_URL

    def _get(self, path: str, params: dict | None = None):
        r = requests.get(self.base + path, params=params or {}, timeout=15)
        if not r.ok:
            raise ExchangeError(f"Binance {path}: {r.status_code} {r.text[:200]}")
        return r.json()

    def price(self, symbol: str) -> float:
        return float(self._get("/api/v3/ticker/price", {"symbol": symbol})["price"])

    def klines(self, symbol: str, interval: str = "4h", limit: int = 120) -> list[float]:
        rows = self._get("/api/v3/klines",
                         {"symbol": symbol, "interval": interval, "limit": limit})
        return [float(r[4]) for r in rows]  # close prices


# ── Paper trading ─────────────────────────────────────────────
class PaperExchange(_BinanceMarketData):
    """Виртуальный счёт в SQLite. Реальные цены, фейковые деньги."""
    name = "paper"

    def __init__(self):
        self._db = sqlite3.connect(str(DB_PATH))
        self._db.execute("""CREATE TABLE IF NOT EXISTS paper_balances (
            asset TEXT PRIMARY KEY, qty REAL NOT NULL DEFAULT 0)""")
        if not self._db.execute("SELECT 1 FROM paper_balances LIMIT 1").fetchone():
            start = float(os.environ.get("PAPER_START_USDT", "1000"))
            self._db.execute("INSERT INTO paper_balances VALUES ('USDT', ?)", (start,))
        self._db.commit()

    def balances(self) -> dict[str, float]:
        rows = self._db.execute("SELECT asset, qty FROM paper_balances WHERE qty > 0")
        return {a: q for a, q in rows}

    def _add(self, asset: str, delta: float):
        self._db.execute(
            "INSERT INTO paper_balances (asset, qty) VALUES (?, ?) "
            "ON CONFLICT(asset) DO UPDATE SET qty = qty + excluded.qty",
            (asset, delta))

    def market_buy(self, symbol: str, quote_usdt: float) -> dict:
        base, quote = split_symbol(symbol)
        if self.balances().get(quote, 0) < quote_usdt:
            raise ExchangeError(f"Недостаточно {quote}")
        px  = self.price(symbol)
        fee = quote_usdt * PAPER_FEE
        qty = (quote_usdt - fee) / px
        self._add(quote, -quote_usdt)
        self._add(base, qty)
        self._db.commit()
        return {"symbol": symbol, "side": "BUY", "qty": qty, "price": px,
                "quote": quote_usdt, "fee": fee, "order_id": f"paper-{uuid.uuid4().hex[:10]}"}

    def market_sell(self, symbol: str, base_qty: float) -> dict:
        base, quote = split_symbol(symbol)
        base_qty = min(base_qty, self.balances().get(base, 0))
        if base_qty <= 0:
            raise ExchangeError(f"Нет {base} для продажи")
        px    = self.price(symbol)
        gross = base_qty * px
        fee   = gross * PAPER_FEE
        self._add(base, -base_qty)
        self._add(quote, gross - fee)
        self._db.commit()
        return {"symbol": symbol, "side": "SELL", "qty": base_qty, "price": px,
                "quote": gross - fee, "fee": fee, "order_id": f"paper-{uuid.uuid4().hex[:10]}"}


# ── Binance (testnet / live) ──────────────────────────────────
class BinanceExchange(_BinanceMarketData):
    """
    Binance Spot REST API.
    testnet: ключи с https://testnet.binance.vision (фейковые деньги)
    live:    ключи с binance.com → API Management (только Read + Spot Trading!)
    """

    def __init__(self, testnet: bool = True):
        self.name   = "binance-testnet" if testnet else "binance-live"
        self.base   = BINANCE_TESTNET if testnet else BINANCE_PUBLIC
        prefix      = "BINANCE_TESTNET_" if testnet else "BINANCE_"
        self.key    = os.environ.get(prefix + "API_KEY", "")
        self.secret = os.environ.get(prefix + "API_SECRET", "")
        if not self.key or not self.secret:
            raise ExchangeError(f"{prefix}API_KEY / {prefix}API_SECRET не заданы в .env")
        self._filters: dict[str, dict] = {}

    def _signed(self, method: str, path: str, params: dict) -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        qs  = urlencode(params)
        sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = requests.request(method, f"{self.base}{path}?{qs}&signature={sig}",
                             headers={"X-MBX-APIKEY": self.key}, timeout=15)
        if not r.ok:
            raise ExchangeError(f"Binance {path}: {r.status_code} {r.text[:200]}")
        return r.json()

    def _symbol_filters(self, symbol: str) -> dict:
        if symbol not in self._filters:
            info = self._get("/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
            f = {x["filterType"]: x for x in info["filters"]}
            self._filters[symbol] = {
                "step":         float(f["LOT_SIZE"]["stepSize"]),
                "min_notional": float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {})
                                      .get("minNotional", 0)),
            }
        return self._filters[symbol]

    def balances(self) -> dict[str, float]:
        acc = self._signed("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        return {b["asset"]: float(b["free"]) + float(b["locked"])
                for b in acc["balances"] if float(b["free"]) + float(b["locked"]) > 0}

    @staticmethod
    def _parse_fill(symbol: str, side: str, o: dict) -> dict:
        qty   = float(o["executedQty"])
        quote = float(o["cummulativeQuoteQty"])
        fee   = sum(float(f["commission"]) for f in o.get("fills", []))
        return {"symbol": symbol, "side": side, "qty": qty,
                "price": quote / qty if qty else 0, "quote": quote,
                "fee": fee, "order_id": str(o["orderId"])}

    def market_buy(self, symbol: str, quote_usdt: float) -> dict:
        f = self._symbol_filters(symbol)
        if quote_usdt < f["min_notional"]:
            raise ExchangeError(f"Сумма {quote_usdt} меньше минимума {f['min_notional']}")
        o = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": f"{quote_usdt:.2f}", "newOrderRespType": "FULL"})
        return self._parse_fill(symbol, "BUY", o)

    def market_sell(self, symbol: str, base_qty: float) -> dict:
        f    = self._symbol_filters(symbol)
        step = f["step"]
        qty  = math.floor(base_qty / step) * step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        if qty <= 0:
            raise ExchangeError("Количество меньше минимального шага лота")
        o = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": f"{qty:.{decimals}f}", "newOrderRespType": "FULL"})
        return self._parse_fill(symbol, "SELL", o)


# ── Revolut X ─────────────────────────────────────────────────
class RevolutXExchange(_BinanceMarketData):
    """
    Revolut X — крипто-биржа Revolut (exchange.revolut.com) с REST API.
    Ключ: Revolut X → Profile → API Keys. Подпись Ed25519.
    Docs: https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api

    Акции/ETF в обычном приложении Revolut API НЕ имеют — там торговать
    ботом нельзя. Только крипта через Revolut X.

    ЭКСПЕРИМЕНТАЛЬНО: не проверено на живом аккаунте. Баланс читается всегда,
    а ордера разрешены только при REVOLUT_X_TRADING=1 — включай после того,
    как проверишь схему ордера по документации на маленькой сумме.
    Цены для стратегии берутся из публичных данных Binance.
    """
    name = "revolut-x"
    api  = "https://revx.revolut.com/api/1.0"

    def __init__(self):
        self.key = os.environ.get("REVOLUT_X_API_KEY", "")
        pem_path = os.environ.get("REVOLUT_X_PRIVATE_KEY_PATH", "")
        if not self.key or not pem_path:
            raise ExchangeError("REVOLUT_X_API_KEY / REVOLUT_X_PRIVATE_KEY_PATH не заданы")
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError:
            raise ExchangeError("pip install cryptography — нужно для подписи Revolut X")
        self._pk = load_pem_private_key(Path(pem_path).read_bytes(), password=None)

    def _request(self, method: str, path: str, query: str = "", body: dict | None = None):
        ts       = str(int(time.time() * 1000))
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        full     = "/api/1.0" + path
        msg      = f"{ts}{method}{full}{query}{body_str}".encode()
        sig      = base64.b64encode(self._pk.sign(msg)).decode()
        url      = self.api + path + (f"?{query}" if query else "")
        r = requests.request(method, url, data=body_str or None, timeout=15, headers={
            "X-Revx-API-Key": self.key, "X-Revx-Timestamp": ts,
            "X-Revx-Signature": sig, "Content-Type": "application/json"})
        if not r.ok:
            raise ExchangeError(f"Revolut X {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.text else {}

    def balances(self) -> dict[str, float]:
        rows = self._request("GET", "/balances")
        return {b["currency"]: float(b.get("total", b.get("available", 0)))
                for b in rows if float(b.get("total", b.get("available", 0))) > 0}

    @staticmethod
    def _rx_symbol(symbol: str) -> str:
        base, quote = split_symbol(symbol)
        return f"{base}-{'USD' if quote in ('USDT', 'USDC') else quote}"

    def _order(self, symbol: str, side: str, size: dict) -> dict:
        if os.environ.get("REVOLUT_X_TRADING") != "1":
            raise ExchangeError("Ордера Revolut X выключены (REVOLUT_X_TRADING != 1)")
        px = self.price(symbol)
        o = self._request("POST", "/orders", body={
            "client_order_id": str(uuid.uuid4()),
            "symbol": self._rx_symbol(symbol), "side": side.lower(),
            "order_configuration": {"market": size}})
        data = o.get("data", o)
        qty  = float(size.get("base_size") or float(size["quote_size"]) / px)
        return {"symbol": symbol, "side": side, "qty": qty, "price": px,
                "quote": qty * px, "fee": 0.0, "order_id": str(data.get("venue_order_id", data.get("id", "")))}

    def market_buy(self, symbol: str, quote_usdt: float) -> dict:
        return self._order(symbol, "BUY", {"quote_size": f"{quote_usdt:.2f}"})

    def market_sell(self, symbol: str, base_qty: float) -> dict:
        return self._order(symbol, "SELL", {"base_size": f"{base_qty:.8f}"})


# ── Factory ───────────────────────────────────────────────────
LIVE_CONFIRM_PHRASE = "I_UNDERSTAND_REAL_MONEY"


def get_exchange():
    """
    FIN_MODE:   paper (default) | testnet | live
    FIN_BROKER: binance (default) | revolut
    live требует FIN_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY
    """
    mode   = os.environ.get("FIN_MODE", "paper").lower()
    broker = os.environ.get("FIN_BROKER", "binance").lower()

    if mode == "paper":
        return PaperExchange()
    if mode == "testnet":
        if broker != "binance":
            raise ExchangeError("Testnet есть только у Binance. Для Revolut используй paper.")
        return BinanceExchange(testnet=True)
    if mode == "live":
        if os.environ.get("FIN_LIVE_CONFIRM") != LIVE_CONFIRM_PHRASE:
            raise ExchangeError(
                f"Live-режим заблокирован. Поставь FIN_LIVE_CONFIRM={LIVE_CONFIRM_PHRASE}")
        return RevolutXExchange() if broker == "revolut" else BinanceExchange(testnet=False)
    raise ExchangeError(f"Неизвестный FIN_MODE={mode}")
