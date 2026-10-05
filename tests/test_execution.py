"""Fase 6: ordens na conta simulada, automação com limites, conector MT5 (falso) e agente HTTP."""
from types import SimpleNamespace

import pytest

from src.core import db
from src.core.config import update_prefs
from src.execution import automation, orders
from src.execution.brokers.mt5_local import Mt5LocalBroker
from src.integrations.tradingfloors import merge_rows
from src.services import alerts, journal, portfolio
from src.services.signals import upsert_signals
from tests.conftest import opcao_row, trade_row

OPEN = {"phase": "open", "label": "Pregão aberto", "detail": "", "is_open": True}


@pytest.fixture()
def paper(tmp_db, monkeypatch):
    monkeypatch.setattr("src.execution.risk.market_status", lambda *a, **k: OPEN)
    monkeypatch.setattr("src.execution.automation.market_status", lambda *a, **k: OPEN)
    monkeypatch.setattr("src.services.sizing.market_status", lambda *a, **k: OPEN)
    update_prefs({"execution": {"mode": "paper"}})
    return tmp_db


def add_signal(id="t1", ticker="NATUK800", preco=0.40, atual=0.40, trader="Sanita", baseline=False, status="OPEN", **kw):
    rows = [trade_row(id, ticker, trader=trader, preco=preco, opcao_id=f"o-{id}", status=status, ts="2099-01-01T13:00:00+00:00", **kw)]
    opc = [opcao_row(f"o-{id}", ticker, trader=trader, preco=preco, atual=atual)] if status == "OPEN" else []
    with db.transaction() as c:
        return upsert_signals(c, merge_rows(rows, opc), baseline=baseline)


def test_mode_off_blocks_sending(tmp_db):
    with pytest.raises(ValueError, match="desligada"):
        orders.submit(ticker="NATUK800", side="BUY", quantity=100, limit_price=0.4)


def test_live_mode_requires_gate(tmp_db, monkeypatch):
    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    update_prefs({"execution": {"mode": "live"}})
    st = orders.execution_state()
    if not st["gate_enabled"]:
        assert not st["can_send"] and "bloqueado" in st["reason"]


def test_paper_order_fills_and_creates_paper_execution(paper):
    add_signal()
    o = orders.submit(ticker="NATUK800", side="BUY", quantity=2500, limit_price=0.41, signal_id="t1")
    assert o["status"] == "filled" and o["filled_qty"] == 2500 and o["avg_fill_price"] == pytest.approx(0.40)
    assert journal.list_executions(account="real") == []
    paper_ex = journal.list_executions(account="paper")
    assert len(paper_ex) == 1 and paper_ex[0]["source"] == "broker" and paper_ex[0]["fees_source"] == "estimate"
    assert portfolio.positions(account="paper")[0]["quantity"] == 2500
    assert any(a["kind"] == "order_filled" for a in alerts.list_alerts())
    # decisão "executado" não é marcada por simulação
    with db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0


def test_paper_limit_waits_until_price_reaches(paper):
    add_signal(atual=0.45)
    o = orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.40)
    assert o["status"] == "open" and o["filled_qty"] == 0
    with db.transaction() as c:
        c.execute("UPDATE quotes SET price = 0.39 WHERE ticker = 'NATUK800'")
    orders.sync_open_orders()
    o = orders.get_order(o["id"])
    assert o["status"] == "filled" and o["avg_fill_price"] == pytest.approx(0.39)
    # idempotente
    orders.sync_open_orders()
    assert len(journal.list_executions(account="paper")) == 1


def test_cancel_open_order(paper):
    add_signal(atual=0.50)
    o = orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.40)
    assert orders.cancel(o["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        orders.cancel(o["id"])


def test_exit_cannot_exceed_position_and_no_naked_sell(paper):
    add_signal()
    orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.40)
    with pytest.raises(ValueError, match="maior que a posição"):
        orders.submit(ticker="NATUK800", side="SELL", quantity=2000, limit_price=0.40, purpose="exit")
    with pytest.raises(ValueError, match="descoberto"):
        orders.submit(ticker="PETR4", side="SELL", quantity=100, limit_price=30, purpose="entry")
    o = orders.submit(ticker="NATUK800", side="SELL", quantity=1000, limit_price=0.40, purpose="exit")
    assert o["status"] == "filled"
    assert portfolio.positions(account="paper") == []


def test_automation_enters_new_signal_and_exits_when_closed(paper, monkeypatch):
    monkeypatch.setattr("src.execution.automation._profiles", lambda: {("sanita", "OPCAO"): {"copyable": "yes"}})
    update_prefs({"execution": {"auto": {"armed": True}}})
    res = add_signal(preco=0.40, atual=0.40)
    acts = automation.run({"new": res["new"]})
    assert [a["type"] for a in acts] == ["entry"]
    pos = portfolio.positions(account="paper")
    assert pos and pos[0]["quantity"] == 2500

    # analista encerra -> automação sai
    with db.transaction() as c:
        c.execute("UPDATE signals SET status='CLOSED', preco_saida=0.60 WHERE id='t1'")
        c.execute("UPDATE quotes SET price=0.60 WHERE ticker='NATUK800'")
    acts = automation.run({"new": []})
    assert [a["type"] for a in acts] == ["exit"]
    assert portfolio.positions(account="paper") == []
    log = automation.recent_log()
    assert {l["action"] for l in log} == {"entrada", "saída"}


def test_automation_respects_limits_and_rules(paper, monkeypatch):
    monkeypatch.setattr("src.execution.automation._profiles", lambda: {("sanita", "OPCAO"): {"copyable": "yes"}})
    update_prefs({"execution": {"auto": {"armed": True, "max_orders_per_day": 1}}})
    r1 = add_signal("t1", "NATUK800")
    r2 = add_signal("t2", "AZZAK185", preco=2.5, atual=2.5)
    acts = automation.run({"new": r1["new"] + r2["new"]})
    assert len(acts) == 1
    blocked = [l for l in automation.recent_log() if l["decision"] == "blocked"]
    assert blocked and "Limite de 1" in blocked[0]["reason"]

    # preço já fugiu do slippage -> não entra
    update_prefs({"execution": {"auto": {"max_orders_per_day": 10}}})
    r3 = add_signal("t3", "CSANJ400", preco=0.20, atual=0.30)
    assert automation.run({"new": r3["new"]}) == []
    assert "acima" in automation.recent_log(1)[0]["reason"]

    # sinal de analista não copiável
    monkeypatch.setattr("src.execution.automation._profiles", lambda: {("sanita", "OPCAO"): {"copyable": "no"}})
    r4 = add_signal("t4", "BBASJ23", preco=0.6, atual=0.6)
    assert automation.run({"new": r4["new"]}) == []


def test_panic_disarms_and_cancels(paper):
    update_prefs({"execution": {"auto": {"armed": True}}})
    add_signal(atual=0.55)
    orders.submit(ticker="NATUK800", side="BUY", quantity=1000, limit_price=0.40)
    assert automation.panic()["cancelled"] == 1
    assert not orders.execution_state()["armed"]


# ---------------------------------------------------------------- MT5 falso
class FakeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_REMOVE = 1, 5, 8
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    ORDER_TIME_DAY, ORDER_FILLING_RETURN = 1, 2
    TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE_PARTIAL = 10009, 10008, 10010

    def __init__(self):
        self.sent, self.live, self.deals, self.next = [], {}, [], 500

    def initialize(self, **kw): return True
    def terminal_info(self): return SimpleNamespace(connected=True, trade_allowed=True)
    def account_info(self): return SimpleNamespace(login=123, server="XP-PRD", company="XP", balance=10000.0, equity=10000.0,
                                                   margin_free=9000.0, currency="BRL", trade_allowed=True)
    def last_error(self): return (0, "ok")
    def symbol_select(self, s, on): return s != "INEXISTENTE"
    def symbol_info_tick(self, s): return SimpleNamespace(bid=0.39, ask=0.41, last=0.40, time=1790000000)
    def symbol_info(self, s): return SimpleNamespace(price_change=0.0)

    def order_send(self, req):
        self.sent.append(req)
        if req["action"] == self.TRADE_ACTION_REMOVE:
            self.live.pop(req["order"], None)
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=req["order"], deal=0, comment="ok")
        self.next += 1
        oid = self.next
        if req["price"] >= 0.41:  # executa na hora
            self.deals.append(SimpleNamespace(ticket=9000 + oid, order=oid, volume=req["volume"], price=0.41, commission=-1.0, fee=-0.2, time=1790000000))
        else:
            self.live[oid] = SimpleNamespace(volume_initial=req["volume"], volume_current=req["volume"])
        return SimpleNamespace(retcode=self.TRADE_RETCODE_PLACED, order=oid, deal=0, comment="Request executed")

    def history_deals_get(self, a, b, group=None): return self.deals
    def orders_get(self, ticket): return [self.live[ticket]] if ticket in self.live else []
    def history_orders_get(self, ticket): return [SimpleNamespace(state=4 if any(d.order == ticket for d in self.deals) else 2)]


def test_mt5_local_broker_mapping():
    fake = FakeMT5()
    b = Mt5LocalBroker(mt5_module=fake)
    h = b.health()
    assert h["ok"] and h["account"]["login"] == 123
    r = b.place_order("NATUK800", "BUY", 1000, "limit", 0.41)
    assert r["accepted"] and r["status"] == "filled" and r["fills"][0]["fees"] == pytest.approx(1.2)
    assert fake.sent[0]["type"] == fake.ORDER_TYPE_BUY_LIMIT and fake.sent[0]["type_filling"] == fake.ORDER_FILLING_RETURN
    r2 = b.place_order("NATUK800", "BUY", 1000, "limit", 0.35)
    assert r2["status"] == "open"
    assert b.cancel_order(r2["broker_order_id"], "NATUK800")["ok"]
    assert b.place_order("INEXISTENTE", "BUY", 100, "limit", 1.0)["status"] == "rejected"


def test_agent_and_remote_broker_roundtrip(monkeypatch):
    from src.execution.agent import create_agent
    from src.execution.brokers.mt5_remote import Mt5RemoteBroker

    token = "t" * 20
    app = create_agent(Mt5LocalBroker(mt5_module=FakeMT5()), token)
    client = app.test_client()
    assert client.get("/health").status_code == 401

    class Adapter:
        headers = {}

        def request(self, method, url, timeout=None, json=None, params=None):
            path = url.replace("http://agente", "")
            r = client.open(path, method=method, json=json, query_string=params, headers=self.headers)
            return SimpleNamespace(status_code=r.status_code, json=lambda: r.get_json())

    remote = Mt5RemoteBroker("http://agente", token, session=Adapter())
    assert remote.health()["ok"]
    r = remote.place_order("NATUK800", "BUY", 500, "limit", 0.45)
    assert r["status"] == "filled"
    assert remote.order_status(r["broker_order_id"], "NATUK800")["filled_qty"] == 500
    bad = Mt5RemoteBroker("http://agente", "x" * 20, session=Adapter())
    assert bad.health()["ok"] is False
