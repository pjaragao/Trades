"""Teste de fumaça das APIs com o Flask test client (sem rede: monitor desligado)."""
import pytest

from src.core import db
from src.integrations.tradingfloors import merge_rows
from src.services.signals import upsert_signals
from tests.conftest import opcao_row, trade_row


@pytest.fixture()
def client(tmp_db):
    from web.app import create_app

    app = create_app(start_monitor=False, db_path=tmp_db)
    app.testing = True
    with db.transaction() as c:
        upsert_signals(c, merge_rows(
            [trade_row("t1", "NATUK800", preco=0.38, opcao_id="o1", ts="2099-01-01T14:00:00+00:00"),
             trade_row("t2", "WINFUT", trader="Brondi", tipo="Futuros (B3)", produto="Trading Floor", preco=188000)],
            [opcao_row("o1", "NATUK800", preco=0.38, atual=0.40)],
        ))
    return app.test_client()


def test_pages_and_status(client):
    assert client.get("/").status_code == 200
    st = client.get("/api/status").get_json()
    assert {"monitor", "market", "portfolio", "alerts", "execution"} <= set(st)
    assert st["execution"]["enabled"] is False


def test_signals_followed_scope_and_ticket(client):
    data = client.get("/api/signals?status=open&scope=followed").get_json()
    assert [s["ticker"] for s in data["items"]] == ["NATUK800"]
    all_ = client.get("/api/signals?status=open&scope=all").get_json()
    assert all_["total"] == 2
    det = client.get("/api/signals/t1").get_json()
    assert det["ticket"]["quantity"] == 2500 and det["ticket"]["limit_price"] == 0.39  # 0,40 passa do slippage de 5%
    t = client.get("/api/signals/t1/ticket?quantity=1000&limit_price=0,39").get_json()
    assert t["quantity"] == 1000 and t["limit_price"] == 0.39


def test_full_manual_flow(client):
    today = client.get("/api/today").get_json()
    assert [s["id"] for s in today["new_signals"]] == ["t1"]

    r = client.post("/api/executions", json={"signal_id": "t1", "ticker": "NATUK800", "side": "BUY", "quantity": 2500,
                                             "price": 0.39, "fees": 0.63, "executed_at": "2026-10-05T11:00:00-03:00"})
    assert r.status_code == 201
    today = client.get("/api/today").get_json()
    assert today["new_signals"] == []
    pos = client.get("/api/portfolio").get_json()["positions"]
    assert len(pos) == 1 and pos[0]["quantity"] == 2500 and pos[0]["signal"]["id"] == "t1"
    assert pos[0]["unrealized_pnl"] == pytest.approx((0.40 - (0.39 * 2500 + 0.63) / 2500) * 2500, abs=0.01)

    # analista encerra -> saída pendente
    with db.transaction() as c:
        c.execute("UPDATE signals SET status='CLOSED', preco_saida=0.60 WHERE id='t1'")
    today = client.get("/api/today").get_json()
    assert len(today["exits_pending"]) == 1
    assert "VENDA NATUK800" in today["exits_pending"][0]["exit_ticket"]["copy_text"]

    r = client.post("/api/executions", json={"signal_id": "t1", "ticker": "NATUK800", "side": "SELL", "quantity": 2500,
                                             "price": 0.58, "fees": 0.94, "executed_at": "2026-10-07T11:00:00-03:00"})
    assert r.status_code == 201
    res = client.get("/api/results").get_json()
    assert res["trades"] == 1
    tr = res["closed_trades"][0]
    assert tr["trader"] == "Sanita" and tr["realized_pnl"] == pytest.approx(2500 * 0.19 - 0.63 - 0.94, abs=0.01)
    assert tr["entry_slippage_pct"] == pytest.approx(2.63, abs=0.01)
    tax = client.get("/api/results/tax").get_json()
    assert tax["months"][-1]["month"] >= "2026-10"
    csv = client.get("/api/export/operacoes.csv")
    assert csv.status_code == 200 and "NATUK800" in csv.get_data(as_text=True)


def test_decisions_and_validation(client):
    assert client.post("/api/signals/t1/decision", json={"status": "ignored", "reason": "caro"}).status_code == 200
    assert client.get("/api/today").get_json()["new_signals"] == []
    assert client.post("/api/signals/t1/decision", json={"status": "snoozed", "remind_minutes": 30}).status_code == 200
    assert client.post("/api/signals/t1/decision", json={"status": "clear"}).status_code == 200
    assert client.post("/api/signals/t1/decision", json={"status": "xyz"}).status_code == 400
    assert client.get("/api/signals/nao-existe").status_code == 404
    bad = client.post("/api/executions", json={"ticker": "PETR4", "side": "SELL", "quantity": 100, "price": 30})
    assert bad.status_code == 400 and "descoberto" in bad.get_json()["error"]


def test_settings_roundtrip(client):
    s = client.get("/api/settings").get_json()
    assert s["prefs"]["sizing"]["value_per_trade"] == 1000.0
    s2 = client.put("/api/settings", json={"sizing": {"value_per_trade": 2000, "mode": "invalido"}, "follow": {"traders": ["Ferri"]}}).get_json()
    assert s2["prefs"]["sizing"]["value_per_trade"] == 2000.0
    assert s2["prefs"]["sizing"]["mode"] == "fixed_capital"
    assert client.get("/api/signals?status=open").get_json()["items"] == []
