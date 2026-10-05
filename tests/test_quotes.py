"""Cotações ao vivo: feed (fonte falsa), prioridade sobre o TradingFloors, boleta com bid/ask, agente e SSE."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.core import db
from src.core.config import update_prefs
from src.execution import orders
from src.execution.brokers.mt5_local import Mt5LocalBroker
from src.integrations.market_data import ProviderError
from src.services import journal, portfolio, quotes
from src.services.signals import get_signal
from src.services.sizing import build_ticket
from tests.test_execution import OPEN, FakeMT5, add_signal

FLAGS = {"mt5": True, "brapi": False, "provider": "mt5", "mt5_ready": True, "interval": 2.0, "closed_interval": 300.0,
         "brapi_token": "", "brapi_daily_budget": 450, "brapi_min_interval": 1800.0, "brapi_reserve": 1000, "max_tickers": 60}


class FakeProvider:
    name, label, realtime, delay_minutes = "mt5", "MT5", True, 0

    def __init__(self, book=None):
        self.book = dict(book or {})
        self.calls = []
        self.fail = None

    def supports(self, ticker):
        return True

    def fetch(self, tickers):
        self.calls.append(list(tickers))
        if self.fail:
            raise ProviderError(self.fail)
        return {t: self.book.get(t) for t in tickers}


@pytest.fixture()
def feed(tmp_db, monkeypatch):
    provider = FakeProvider({"NATUK800": {"bid": 0.42, "ask": 0.44, "last": 0.43, "time": None, "change_pct": 5.0}})
    f = quotes.QuoteFeed(provider_factory=lambda flags, on_request=None: (provider, None), flags_loader=lambda: dict(FLAGS))
    f.provider = provider
    monkeypatch.setattr(quotes, "_feed", f)
    monkeypatch.setattr("src.services.sizing.market_status", lambda *a, **k: OPEN)
    return f


def _quote_row(ticker):
    with db.connection() as c:
        r = c.execute("SELECT * FROM quotes WHERE ticker = ?", (ticker,)).fetchone()
        return dict(r) if r else None


def test_feed_watches_signals_and_positions_and_stores_book(feed):
    add_signal()  # sinal aberto de analista seguido (TradingFloors: 0,40)
    journal.add_execution({"ticker": "PETR4", "side": "BUY", "quantity": 100, "price": 30.0, "fees": 0, "executed_at": "2026-10-01T11:00"})
    feed.provider.book["PETR4"] = {"bid": 31.0, "ask": 31.02, "last": 31.01, "time": None, "change_pct": None}
    res = feed.run_once()
    assert set(feed.provider.calls[0]) == {"NATUK800", "PETR4"}
    assert set(res["changed"]) == {"NATUK800", "PETR4"}
    row = _quote_row("NATUK800")
    assert row["source"] == "mt5" and row["price"] == 0.43 and row["bid"] == 0.42 and row["ask"] == 0.44
    st = feed.status()
    assert st["state"] == "live" and st["provider"] == "mt5" and st["watching"] == 2
    # sinal e posição usam a cotação ao vivo
    sig = get_signal("t1")
    assert sig["preco_atual"] == 0.43 and sig["quote"]["live"]
    pos = portfolio.positions()[0]
    assert pos["last_price"] == 31.01 and pos["last_bid"] == 31.0 and pos["quote_live"]
    # segunda rodada sem mudança: nada novo para os navegadores
    v = feed.snapshot()[0]
    assert feed.run_once()["changed"] == [] and feed.snapshot()[0] == v


def test_tradingfloors_does_not_override_fresh_live_quote(feed):
    add_signal()
    feed.run_once()
    add_signal(atual=0.30)  # monitor recebe preço do TradingFloors depois
    assert _quote_row("NATUK800")["source"] == "mt5"
    # cotação ao vivo velha (feed parado): TradingFloors volta a valer
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    with db.transaction() as c:
        c.execute("UPDATE quotes SET updated_at = ? WHERE ticker = 'NATUK800'", (old,))
    add_signal(atual=0.31)
    row = _quote_row("NATUK800")
    assert row["source"] == "tradingfloors" and row["price"] == 0.31 and row["bid"] is None


def test_ticket_uses_ask_for_buy_when_live(feed):
    add_signal(preco=0.40)
    feed.run_once()
    sig = get_signal("t1")
    t = build_ticket(sig, exposure=0)
    assert t["current_price"] == 0.44 and t["price_basis"] == "ask"
    assert t["drift_pct"] == pytest.approx(10.0)


def test_provider_error_sets_error_state_and_backs_off(feed):
    add_signal()
    feed.provider.fail = "Agente MT5 inacessível"
    feed.run_once()
    st = feed.status()
    assert st["state"] == "error" and "inacessível" in st["message"]
    assert feed.interval() > FLAGS["interval"]
    feed.provider.fail = None
    feed.run_once()
    assert feed.status()["state"] == "live" and feed.interval() in (FLAGS["interval"], FLAGS["closed_interval"])


def test_ensure_watches_ticker_opened_on_screen(feed):
    feed.provider.book["VALE3"] = {"bid": 60.0, "ask": 60.02, "last": 60.01, "time": None, "change_pct": None}
    got = feed.ensure(["vale3"])
    assert got["VALE3"]["price"] == 60.01
    assert "VALE3" in feed.watchlist(force=True)


def test_paper_buy_fills_at_ask(feed, monkeypatch):
    monkeypatch.setattr("src.execution.risk.market_status", lambda *a, **k: OPEN)
    update_prefs({"execution": {"mode": "paper"}})
    add_signal()
    feed.run_once()
    o = orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.45)
    assert o["status"] == "filled" and o["avg_fill_price"] == pytest.approx(0.44)
    o2 = orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.43)
    assert o2["status"] == "open"  # limite abaixo da oferta de venda: espera


def test_mt5_server_time_is_converted_to_utc():
    b = Mt5LocalBroker(mt5_module=FakeMT5(), server_utc_offset=-3)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    brt_wall = (now - timedelta(hours=3)).replace(tzinfo=timezone.utc).timestamp()  # horário de Brasília "como se fosse UTC"
    assert datetime.fromisoformat(b._ts(brt_wall)) == now
    # servidor em UTC: a conversão cairia 3 h no futuro, então usa o valor direto
    assert datetime.fromisoformat(b._ts(now.timestamp())) == now


def test_agent_quotes_batch_and_readonly_mode():
    from src.execution.agent import create_agent
    from src.execution.brokers.mt5_remote import Mt5RemoteBroker

    token = "t" * 20
    fake = FakeMT5()
    fake.symbol_info = lambda s: SimpleNamespace(price_change=1.5)
    app = create_agent(Mt5LocalBroker(mt5_module=fake), token, readonly=True)
    client = app.test_client()

    class Adapter:
        headers = {}

        def request(self, method, url, timeout=None, json=None, params=None):
            r = client.open(url.replace("http://agente", ""), method=method, json=json, query_string=params, headers=self.headers)
            return SimpleNamespace(status_code=r.status_code, json=lambda: r.get_json())

    remote = Mt5RemoteBroker("http://agente", token, session=Adapter())
    got = remote.quotes(["NATUK800", "INEXISTENTE"])
    assert got["NATUK800"]["ask"] == 0.41 and got["NATUK800"]["change_pct"] == 1.5 and got["INEXISTENTE"] is None
    h = remote.health()
    assert h["readonly"] and h["connected"] and h["ok"] is False
    with pytest.raises(Exception, match="somente cotações"):
        remote.place_order("NATUK800", "BUY", 100, "limit", 0.4)


def test_stream_and_quotes_endpoints(feed):
    from web.app import create_app

    add_signal()
    feed.run_once()
    client = create_app(start_monitor=False, db_path=db.db_path()).test_client()
    data = client.get("/api/quotes").get_json()
    assert data["quotes"]["NATUK800"]["price"] == 0.43 and data["feed"]["state"] == "live"
    assert client.get("/api/status").get_json()["quotes"]["provider"] == "mt5"
    resp = client.get("/api/stream", buffered=False)
    assert resp.mimetype == "text/event-stream" and resp.headers["X-Accel-Buffering"] == "no"
    chunks = iter(resp.response)
    assert next(chunks).decode().startswith("retry:")
    first = next(chunks).decode()
    assert first.startswith("event: quotes") and '"NATUK800"' in first
    resp.close()


def test_tradingfloors_is_fallback_when_mt5_stops(feed, monkeypatch):
    add_signal(atual=0.40)
    feed.run_once()
    assert get_signal("t1")["preco_atual"] == 0.43
    # MT5 cai: a cotação deixa de valer na hora e o TradingFloors volta a valer no banco após ~2 min
    feed.provider.fail = "Agente MT5 inacessível"
    feed.run_once()
    monkeypatch.setattr(type(feed), "running", property(lambda self: True))
    assert quotes.live_quote("NATUK800") is None
    sig = get_signal("t1")
    assert sig["quote"] is None and sig["quote_fallback"] == "MT5 indisponível"
    t = build_ticket(sig, exposure=0)
    assert any("TradingFloors" in w["text"] for w in t["warnings"])
    three_min = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(timespec="seconds")
    with db.transaction() as c:
        c.execute("UPDATE quotes SET updated_at = ? WHERE ticker = 'NATUK800'", (three_min,))
    add_signal(atual=0.38)
    row = _quote_row("NATUK800")
    assert row["source"] == "tradingfloors" and row["price"] == 0.38
    assert get_signal("t1")["preco_atual"] == 0.38


# ---------------------------------------------------------------- brapi (plano gratuito)
from src.core.market_hours import BRT  # noqa: E402
from src.integrations.market_data import BrapiQuotes  # noqa: E402

TUESDAY = datetime(2026, 10, 6, 10, 30, tzinfo=BRT)  # dia útil; pregão 10:00–16:55


def test_brapi_budget_paces_requests_to_fit_free_plan(tmp_db):
    b = quotes.BrapiBudget(daily_budget=450, min_interval=1800, reserve=1000)
    few = ["PETR4", "VALE3", "BBAS3"]
    assert b.due(few, TUESDAY) == few  # nunca consultadas
    for t in few:
        b.last[t] = TUESDAY.timestamp()
    assert b.due(few, TUESDAY + timedelta(minutes=29)) == []  # brapi só renova a cada 30 min
    assert b.due(few, TUESDAY + timedelta(minutes=31)) == few
    assert b.interval == 1800
    # muitas ações: o intervalo cresce para o teto diário durar até o fechamento
    many = [f"AA{chr(65 + i // 26)}{chr(65 + i % 26)}3" for i in range(80)]
    b.due(many, TUESDAY)
    assert b.interval > 1800
    reqs_per_ticker = (datetime(2026, 10, 6, 16, 55, tzinfo=BRT) - TUESDAY).total_seconds() / b.interval
    assert reqs_per_ticker * len(many) + len(many) <= 450  # cabe no dia, guardando o fechamento
    assert len(b.due(many, TUESDAY)) == quotes.BrapiBudget.MAX_PER_CYCLE


def test_brapi_budget_daily_cap_close_fetch_and_reserve(tmp_db):
    b = quotes.BrapiBudget(daily_budget=10, min_interval=1800, reserve=1000)
    db.kv_set(b._key(TUESDAY.date()), "10")
    assert b.due(["PETR4"], TUESDAY) == []  # teto do dia atingido
    db.kv_set(b._key(TUESDAY.date()), "0")
    b.last["PETR4"] = TUESDAY.replace(hour=16, minute=50).timestamp()
    after_close = TUESDAY.replace(hour=17, minute=45)  # leilão termina 17:00 + 30 min de renovação da brapi
    assert b.due(["PETR4"], after_close) == ["PETR4"]  # uma consulta para o fechamento
    b.last["PETR4"] = after_close.timestamp()
    assert b.due(["PETR4"], after_close + timedelta(hours=3)) == []
    night = TUESDAY.replace(hour=22)
    assert b.due(["PETR4", "VALE3"], night) == ["VALE3"]  # PETR4 já tem o fechamento; VALE3 nunca teve preço
    b.remaining = 900  # janela de 30 dias quase no fim
    assert b.due(["ITUB4"], TUESDAY) == [] and b.status()["paused"]


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload = status, payload
        self.headers = {"x-ratelimit-remaining": "14000", "x-ratelimit-limit": "15000", **(headers or {})}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.headers, self.urls = responses, {}, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.responses[url.rsplit("/", 1)[-1]]


def test_brapi_client_one_ticker_per_request_and_errors():
    ok = FakeResp(200, {"results": [{"regularMarketPrice": 26.76, "regularMarketTime": "2026-10-05T16:40:30.000Z",
                                     "regularMarketChangePercent": 1.2}]})
    calls = []
    sess = FakeSession({"BBAS3": ok, "XXXX3": FakeResp(404, {"error": True}), "VALE3": FakeResp(429, {}, {"retry-after": "120"}),
                        "ITUB4": ok})
    c = BrapiQuotes("token-de-teste", session=sess, on_request=lambda: calls.append(1))
    assert sess.headers["Authorization"] == "Bearer token-de-teste"  # token no cabeçalho, não na URL
    got = c.fetch(["BBAS3", "XXXX3", "VALE3", "ITUB4"])
    assert got["BBAS3"]["last"] == 26.76 and got["XXXX3"] is None
    assert "ITUB4" not in got and c.retry_after == 120  # 429: para na hora
    assert len(sess.urls) == 3 == len(calls) and all("," not in u for u in sess.urls)
    assert c.unsupported == {"XXXX3"} and c.remaining == 14000


class FakeBrapi:
    name, label, realtime, delay_minutes = "brapi", "brapi", False, 30

    def __init__(self, book):
        self.book, self.calls = book, []
        self.unsupported, self.retry_after, self.remaining, self.limit = set(), None, 14000, 15000

    def supports(self, ticker):
        return ticker[-1].isdigit() and len(ticker) <= 6

    def fetch(self, tickers):
        self.calls.append(list(tickers))
        return {t: self.book.get(t) for t in tickers}


def test_stocks_fall_back_to_brapi_when_mt5_is_down(tmp_db, monkeypatch):
    rt = FakeProvider({"PETR4": {"bid": 31.0, "ask": 31.02, "last": 31.01, "time": None, "change_pct": None}})
    slow = FakeBrapi({"PETR4": {"bid": None, "ask": None, "last": 30.9, "time": "2026-10-05T16:40:30.000Z", "change_pct": 1.0}})
    flags = {**FLAGS, "brapi": True, "brapi_token": "x"}
    f = quotes.QuoteFeed(provider_factory=lambda fl, cb=None: (rt, slow), flags_loader=lambda: dict(flags))
    monkeypatch.setattr(quotes, "_feed", f)
    journal.add_execution({"ticker": "PETR4", "side": "BUY", "quantity": 100, "price": 30.0, "fees": 0, "executed_at": "2026-10-01T11:00"})
    f.run_once()
    assert slow.calls == []  # MT5 ao vivo: a brapi não gasta requisição
    assert quotes.live_quote("PETR4")["source"] == "mt5"
    rt.fail = "Agente MT5 inacessível"
    f.run_once()
    assert slow.calls == [["PETR4"]]
    q = quotes.live_quote("PETR4")
    assert q["source"] == "brapi" and q["price"] == 30.9 and not q["live"]
    st = f.status()
    assert st["state"] == "error" and "brapi" in st["message"] and st["brapi"]["used_today"] == 0  # contador é do provedor real
    assert portfolio.positions()[0]["last_price"] == 30.9
