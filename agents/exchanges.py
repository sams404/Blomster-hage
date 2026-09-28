"""
Биржи для Crocus Aurum — единый интерфейс. Работаем с активами (BTC, ETH),
каждая биржа сама знает свою пару и валюту расчёта.

  Binance   — пары BTCUSDT, расчёт в USDT
  Revolut X — пары BTC-USD, расчёт в USD (крипто-биржа Revolut, регион EEA)

Режимы (на каждую биржу отдельно):
  paper    — виртуальный счёт на реальных ценах ЭТОЙ биржи (без риска)
  testnet  — только Binance: настоящие ордера, фейковые деньги
  live     — реальные деньги (нужен FIN_LIVE_CONFIRM)

Интерфейс:
  price(asset) -> float            closes(asset, interval) -> list[float]
  balances() -> {asset: qty}       market_buy(asset, quote_amount) -> fill
  market_sell(asset, qty) -> fill

fill = {"symbol", "asset", "side", "qty", "price", "quote", "fee", "order_id"}

ВАЖНО: здесь НЕТ кода вывода средств. API-ключи создавай только с правами
чтения и спот-торговли, без Withdraw.
"""
import os, time, hmac, hashlib, json, math, sqlite3, uuid, base64
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "blomster.db"

BINANCE_API     = "https://api.binance.com"
BINANCE_TESTNET = "https://testnet.binance.vision"
# Официальное зеркало Binance только для рыночных данных — без гео-блоков
BINANCE_DATA    = os.environ.get("FIN_MARKET_DATA_URL", "https://data-api.binance.vision")
REVOLUT_X_API   = "https://revx.revolut.com/api"

PAPER_FEE = {"binance": 0.001, "revolut": 0.0009}  # taker fee для симуляции
LIVE_CONFIRM_PHRASE = "I_UNDERSTAND_REAL_MONEY"
BROKERS = ("binance", "revolut")


class ExchangeError(Exception):
    pass


def _floor(value: float, step: str) -> Decimal:
    """Округлить вниз до шага лота биржи."""
    s = Decimal(step)
    return (Decimal(str(value)) / s).to_integral_value(ROUND_DOWN) * s


def _http(method: str, url: str, who: str, **kw):
    r = requests.request(method, url, timeout=15, **kw)
    if not r.ok:
        raise ExchangeError(f"{who} {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


# ── Market data ───────────────────────────────────────────────
class BinanceData:
    broker = "binance"
    cash   = "USDT"
    data_url = BINANCE_DATA

    def pair(self, asset: str) -> str:
        return f"{asset}{self.cash}"

    def price(self, asset: str) -> float:
        if asset in (self.cash, "USD"):
            return 1.0
        j = _http("GET", f"{self.data_url}/api/v3/ticker/price", "Binance",
                  params={"symbol": self.pair(asset)})
        return float(j["price"])

    def closes(self, asset: str, interval: str = "4h", limit: int = 120) -> list[float]:
        rows = _http("GET", f"{self.data_url}/api/v3/klines", "Binance",
                     params={"symbol": self.pair(asset), "interval": interval, "limit": limit})
        return [float(r[4]) for r in rows]


class RevolutData:
    broker = "revolut"
    cash   = os.environ.get("REVOLUT_X_QUOTE", "USD")
    _INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
                  "4h": 240, "1d": 1440, "1w": 10080}
    _pairs: dict = {}

    def pair(self, asset: str) -> str:
        return f"{asset}-{self.cash}"

    def pair_info(self, asset: str) -> dict:
        if not RevolutData._pairs:
            j = _http("GET", f"{REVOLUT_X_API}/1.0/public/configuration/pairs", "Revolut X")
            RevolutData._pairs = j.get("data", j)
        info = RevolutData._pairs.get(f"{asset}/{self.cash}")
        if not info or info.get("status") != "active":
            raise ExchangeError(f"Revolut X: пара {asset}/{self.cash} недоступна")
        return info

    def price(self, asset: str) -> float:
        if asset in (self.cash, "USDT", "USDC"):
            return 1.0
        j = _http("GET", f"{REVOLUT_X_API}/1.0/public/tickers", "Revolut X")
        for t in j.get("data", []):
            if t["symbol"] == f"{asset}/{self.cash}":
                return float(t["mid"])
        raise ExchangeError(f"Revolut X: нет цены {asset}/{self.cash}")

    def closes(self, asset: str, interval: str = "4h", limit: int = 120) -> list[float]:
        mins = self._INTERVALS.get(interval)
        if not mins:
            raise ExchangeError(f"Revolut X: интервал {interval} не поддерживается")
        j = _http("GET", f"{REVOLUT_X_API}/1.0/public/candles/{self.pair(asset)}",
                  "Revolut X", params={"interval": mins})
        rows = sorted(j.get("data", []), key=lambda c: c["start"])
        return [float(c["close"]) for c in rows[-limit:]]


# ── Paper trading ─────────────────────────────────────────────
class PaperExchange:
    """Виртуальный счёт в SQLite на реальных ценах выбранной биржи."""

    def __init__(self, data):
        self.data   = data
        self.broker = data.broker
        self.cash   = data.cash
        self.name   = f"{self.broker}-paper"
        self._db = sqlite3.connect(str(DB_PATH))
        self._db.execute("""CREATE TABLE IF NOT EXISTS paper_accounts (
            account TEXT NOT NULL, asset TEXT NOT NULL, qty REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (account, asset))""")
        if not self._db.execute("SELECT 1 FROM paper_accounts WHERE account=?",
                                (self.broker,)).fetchone():
            start = float(os.environ.get("PAPER_START_USDT", "1000"))
            self._db.execute("INSERT INTO paper_accounts VALUES (?, ?, ?)",
                             (self.broker, self.cash, start))
        self._db.commit()

    def pair(self, asset):   return self.data.pair(asset)
    def price(self, asset):  return self.data.price(asset)
    def closes(self, asset, interval="4h", limit=120):
        return self.data.closes(asset, interval, limit)

    def balances(self) -> dict[str, float]:
        rows = self._db.execute(
            "SELECT asset, qty FROM paper_accounts WHERE account=? AND qty > 1e-12", (self.broker,))
        return {a: q for a, q in rows}

    def _add(self, asset: str, delta: float):
        self._db.execute(
            "INSERT INTO paper_accounts (account, asset, qty) VALUES (?, ?, ?) "
            "ON CONFLICT(account, asset) DO UPDATE SET qty = qty + excluded.qty",
            (self.broker, asset, delta))

    def market_buy(self, asset: str, quote_amount: float) -> dict:
        if self.balances().get(self.cash, 0) < quote_amount:
            raise ExchangeError(f"Недостаточно {self.cash}")
        px  = self.price(asset)
        fee = quote_amount * PAPER_FEE[self.broker]
        qty = (quote_amount - fee) / px
        self._add(self.cash, -quote_amount)
        self._add(asset, qty)
        self._db.commit()
        return {"symbol": self.pair(asset), "asset": asset, "side": "BUY", "qty": qty,
                "price": px, "quote": quote_amount, "fee": fee,
                "order_id": f"paper-{uuid.uuid4().hex[:10]}"}

    def market_sell(self, asset: str, qty: float) -> dict:
        qty = min(qty, self.balances().get(asset, 0))
        if qty <= 0:
            raise ExchangeError(f"Нет {asset} для продажи")
        px    = self.price(asset)
        gross = qty * px
        fee   = gross * PAPER_FEE[self.broker]
        self._add(asset, -qty)
        self._add(self.cash, gross - fee)
        self._db.commit()
        return {"symbol": self.pair(asset), "asset": asset, "side": "SELL", "qty": qty,
                "price": px, "quote": gross - fee, "fee": fee,
                "order_id": f"paper-{uuid.uuid4().hex[:10]}"}


# ── Binance (testnet / live) ──────────────────────────────────
class BinanceExchange(BinanceData):
    """
    Binance Spot REST API.
    testnet: ключи с https://testnet.binance.vision
    live:    binance.com → API Management: Enable Reading + Spot Trading,
             БЕЗ Withdrawals, с ограничением по IP.
    """

    def __init__(self, testnet: bool = True):
        self.name     = "binance-testnet" if testnet else "binance-live"
        self.api      = BINANCE_TESTNET if testnet else BINANCE_API
        self.data_url = self.api  # свечи/цены с той же площадки, где торгуем
        prefix        = "BINANCE_TESTNET_" if testnet else "BINANCE_"
        self.key      = os.environ.get(prefix + "API_KEY", "")
        self.secret   = os.environ.get(prefix + "API_SECRET", "")
        if not self.key or not self.secret:
            raise ExchangeError(f"{prefix}API_KEY / {prefix}API_SECRET не заданы в .env")
        self._filters: dict[str, dict] = {}

    def _signed(self, method: str, path: str, params: dict) -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        qs  = urlencode(params)
        sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return _http(method, f"{self.api}{path}?{qs}&signature={sig}", "Binance",
                     headers={"X-MBX-APIKEY": self.key})

    def _symbol_filters(self, symbol: str) -> dict:
        if symbol not in self._filters:
            info = _http("GET", f"{self.api}/api/v3/exchangeInfo", "Binance",
                         params={"symbol": symbol})["symbols"][0]
            f = {x["filterType"]: x for x in info["filters"]}
            self._filters[symbol] = {
                "step": f["LOT_SIZE"]["stepSize"].rstrip("0"),
                "min_notional": float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {})
                                      .get("minNotional", 0)),
            }
        return self._filters[symbol]

    def balances(self) -> dict[str, float]:
        acc = self._signed("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        return {b["asset"]: float(b["free"]) + float(b["locked"])
                for b in acc["balances"] if float(b["free"]) + float(b["locked"]) > 0}

    def _fill(self, asset: str, side: str, o: dict) -> dict:
        qty   = float(o["executedQty"])
        quote = float(o["cummulativeQuoteQty"])
        # комиссия может быть в BNB/базе — приводим к валюте расчёта приблизительно
        fee = 0.0
        for f in o.get("fills", []):
            c = float(f["commission"])
            fee += c if f["commissionAsset"] == self.cash else c * float(f["price"]) \
                if f["commissionAsset"] == asset else 0.0
        return {"symbol": self.pair(asset), "asset": asset, "side": side, "qty": qty,
                "price": quote / qty if qty else 0, "quote": quote, "fee": fee,
                "order_id": str(o["orderId"])}

    def market_buy(self, asset: str, quote_amount: float) -> dict:
        symbol = self.pair(asset)
        f = self._symbol_filters(symbol)
        if quote_amount < f["min_notional"]:
            raise ExchangeError(f"Сумма {quote_amount:.2f} меньше минимума {f['min_notional']}")
        o = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": f"{quote_amount:.2f}", "newOrderRespType": "FULL"})
        return self._fill(asset, "BUY", o)

    def market_sell(self, asset: str, qty: float) -> dict:
        symbol = self.pair(asset)
        q = _floor(qty, self._symbol_filters(symbol)["step"])
        if q <= 0:
            raise ExchangeError("Количество меньше минимального шага лота")
        o = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": format(q, "f"), "newOrderRespType": "FULL"})
        return self._fill(asset, "SELL", o)


# ── Revolut X (live) ──────────────────────────────────────────
class RevolutXExchange(RevolutData):
    """
    Revolut X REST API — схема сверена с официальной OpenAPI
    (developer.revolut.com/docs/x-api). Подпись Ed25519:
      message = timestamp + METHOD + /api/path + query + minified_json_body

    Ключ: exchange.revolut.com → Profile → API keys. Сначала
    `openssl genpkey -algorithm ed25519 -out revolut_x_private.pem`,
    публичный ключ загружаешь в Revolut X, приватный остаётся у тебя.
    Акции в обычном приложении Revolut API не имеют — только крипта здесь.
    """
    name = "revolut-live"

    def __init__(self):
        self.key = os.environ.get("REVOLUT_X_API_KEY", "")
        pem_path = os.environ.get("REVOLUT_X_PRIVATE_KEY_PATH", "")
        if not self.key or not pem_path:
            raise ExchangeError("REVOLUT_X_API_KEY / REVOLUT_X_PRIVATE_KEY_PATH не заданы в .env")
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError:
            raise ExchangeError("pip install cryptography — нужно для подписи Revolut X")
        self._pk = load_pem_private_key(Path(pem_path).read_bytes(), password=None)

    def _headers(self, method: str, path: str, query: str, body: str) -> dict:
        ts  = str(int(time.time() * 1000))
        msg = f"{ts}{method}/api{path}{query}{body}".encode()
        return {"X-Revx-API-Key": self.key, "X-Revx-Timestamp": ts,
                "X-Revx-Signature": base64.b64encode(self._pk.sign(msg)).decode(),
                "Content-Type": "application/json"}

    def _request(self, method: str, path: str, params: dict | None = None,
                 body: dict | None = None):
        query    = urlencode(params or {})
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        url      = f"{REVOLUT_X_API}{path}" + (f"?{query}" if query else "")
        return _http(method, url, "Revolut X", data=body_str or None,
                     headers=self._headers(method, path, query, body_str))

    def balances(self) -> dict[str, float]:
        rows = self._request("GET", "/1.0/balances")
        return {b["currency"]: float(b["total"]) for b in rows if float(b["total"]) > 0}

    def _order(self, asset: str, side: str, size: dict) -> dict:
        placed = self._request("POST", "/1.0/orders", body={
            "client_order_id": str(uuid.uuid4()), "symbol": self.pair(asset),
            "side": side.lower(), "order_configuration": {"market": size}})
        oid = placed["data"]["venue_order_id"]
        if placed["data"].get("state") == "rejected":
            raise ExchangeError("Revolut X отклонил ордер")
        # Ждём исполнения рыночного ордера, чтобы знать реальные цифры
        for _ in range(10):
            o = self._request("GET", f"/1.0/orders/{oid}")["data"]
            if o["status"] in ("filled", "cancelled", "rejected"):
                break
            time.sleep(1)
        if o["status"] == "rejected" or float(o.get("filled_quantity") or 0) == 0:
            raise ExchangeError(f"Revolut X: ордер {o['status']} {o.get('reject_reason', '')}")
        qty = float(o["filled_quantity"])
        px  = float(o.get("average_fill_price") or 0) or self.price(asset)
        return {"symbol": self.pair(asset), "asset": asset, "side": side, "qty": qty,
                "price": px, "quote": float(o.get("filled_amount") or qty * px),
                "fee": 0.0, "order_id": oid}

    def market_buy(self, asset: str, quote_amount: float) -> dict:
        info = self.pair_info(asset)
        q = _floor(quote_amount, info["quote_step"])
        if q < Decimal(info["min_order_size_quote"]):
            raise ExchangeError(f"Сумма меньше минимума {info['min_order_size_quote']} {self.cash}")
        return self._order(asset, "BUY", {"quote_size": format(q, "f")})

    def market_sell(self, asset: str, qty: float) -> dict:
        info = self.pair_info(asset)
        q = _floor(qty, info["base_step"])
        if q < Decimal(info["min_order_size"]):
            raise ExchangeError("Количество меньше минимального размера ордера")
        return self._order(asset, "SELL", {"base_size": format(q, "f")})


# ── Factory ───────────────────────────────────────────────────
def active_brokers() -> list[str]:
    """FIN_BROKERS=binance,revolut (старое FIN_BROKER тоже понимаем)."""
    raw = os.environ.get("FIN_BROKERS") or os.environ.get("FIN_BROKER", "binance")
    out = [b.strip().lower() for b in raw.split(",") if b.strip()]
    bad = [b for b in out if b not in BROKERS]
    if bad:
        raise ExchangeError(f"Неизвестные биржи: {bad}. Доступны: {BROKERS}")
    return out


def broker_mode(broker: str) -> str:
    """FIN_MODE_BINANCE / FIN_MODE_REVOLUT перекрывают общий FIN_MODE."""
    return os.environ.get(f"FIN_MODE_{broker.upper()}", os.environ.get("FIN_MODE", "paper")).lower()


def get_exchange(broker: str):
    mode = broker_mode(broker)
    data = BinanceData() if broker == "binance" else RevolutData()

    if mode == "paper":
        return PaperExchange(data)
    if mode == "testnet":
        if broker != "binance":
            raise ExchangeError("У Revolut X нет testnet — используй FIN_MODE_REVOLUT=paper")
        return BinanceExchange(testnet=True)
    if mode == "live":
        if os.environ.get("FIN_LIVE_CONFIRM") != LIVE_CONFIRM_PHRASE:
            raise ExchangeError(
                f"Live заблокирован: поставь FIN_LIVE_CONFIRM={LIVE_CONFIRM_PHRASE}")
        return RevolutXExchange() if broker == "revolut" else BinanceExchange(testnet=False)
    raise ExchangeError(f"Неизвестный режим {mode} для {broker}")
