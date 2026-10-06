"""Trade semelhante em aberto: o sinal aparece com aviso (caso ROXOK135 da Sanita x ROXOJ12 do Ferri em carteira)."""
from src.core import db
from src.integrations.tradingfloors import merge_rows
from src.services import alerts, journal, portfolio, similar
from src.services.signal_monitor import SignalMonitor
from src.services.signals import get_signal, upsert_signals
from tests.conftest import FakeAPI, trade_row


def add_signal(id, ticker, trader="Sanita", lado="BUY", preco=0.64, ts="2026-10-06T16:59:00+00:00"):
    with db.transaction() as c:
        upsert_signals(c, merge_rows([trade_row(id, ticker, trader=trader, lado=lado, preco=preco, ts=ts)], []), baseline=False)


def hold(ticker, qty=1000, price=0.90, signal_id=None, side="BUY"):
    return journal.add_execution({"ticker": ticker, "side": side, "quantity": qty, "price": price, "fees": 0.0,
                                  "executed_at": "2026-10-05T16:42:00-03:00", "signal_id": signal_id}, allow_short=True)


def test_direction_and_relations(tmp_db):
    add_signal("ferri", "ROXOJ12", trader="Ferri", preco=1.0, ts="2026-10-05T19:42:00+00:00")
    hold("ROXOJ12", signal_id="ferri")
    hold("ROXOV135", qty=500, price=0.30)  # PUT de ROXO comprada: aposta na queda
    hold("ROXO34", qty=100, price=13.0)
    add_signal("sanita", "ROXOK135")
    sig = get_signal("sanita")
    rel = {x["ticker"]: x["relation"] for x in similar.find(sig, portfolio.positions())}
    assert rel == {"ROXOJ12": "same_direction", "ROXO34": "same_direction", "ROXOV135": "opposite"}
    first = similar.find(sig, portfolio.positions())[0]
    assert first["trader"] == "Ferri" and first["kind"] == "CALL" and first["underlying"] == "ROXO34"
    # o próprio trade (posição vinculada ao sinal) não é "semelhante"
    assert all(x["ticker"] != "ROXOJ12" for x in similar.find(get_signal("ferri"), portfolio.positions()))
    # vender CALL = baixa; comprar PUT = baixa
    assert similar.direction("ROXOK135", "OPCAO", long=False) == -1 and similar.direction("ROXOV135", "OPCAO", long=True) == -1


def test_today_shows_signal_with_warning_and_same_ticker_can_be_linked(tmp_db):
    from web.app import create_app

    add_signal("ferri", "ROXOJ12", trader="Ferri", preco=1.0, ts="2026-10-05T19:42:00+00:00")
    hold("ROXOJ12", signal_id="ferri")
    add_signal("sanita", "ROXOK135", ts="2099-01-01T13:00:00+00:00")
    add_signal("dup", "ROXOJ12", trader="Sanita", preco=0.95, ts="2099-01-01T13:00:00+00:00")
    client = create_app(start_monitor=False, db_path=db.db_path()).test_client()
    today = {s["id"]: s for s in client.get("/api/today").get_json()["new_signals"]}
    assert "ferri" not in today  # já é minha posição
    assert today["sanita"]["similar"][0]["ticker"] == "ROXOJ12" and today["sanita"]["similar"][0]["relation"] == "same_direction"
    assert today["dup"]["similar"][0]["relation"] == "same_ticker"  # mesmo ativo de outro analista: aparece, com aviso
    assert client.get("/api/signals/sanita").get_json()["similar"][0]["ticker"] == "ROXOJ12"
    # posição manual (sem sinal) no mesmo ativo: "É este trade" vincula e dá baixa
    hold("PETRK420", qty=200, price=1.0)
    add_signal("petr", "PETRK420", ts="2099-01-01T13:00:00+00:00")
    cyc = next(p for p in portfolio.positions() if p["ticker"] == "PETRK420")["cycle_id"]
    r = client.post("/api/signals/petr/link-position", json={"cycle_id": cyc})
    assert r.status_code == 200 and r.get_json()["linked"] == 1
    assert get_signal("petr")["decision"]["status"] == "executed"


def test_new_signal_alert_mentions_similar_position(tmp_db):
    api = FakeAPI([trade_row("ferri", "ROXOJ12", trader="Ferri", preco=1.0)])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()
    hold("ROXOJ12", signal_id="ferri")
    api.trades.append(trade_row("sanita", "ROXOK135", trader="Sanita", preco=0.64, ts="2026-10-06T16:59:00+00:00"))
    m.run_cycle()
    a = next(a for a in alerts.list_alerts() if a["kind"] == "new_signal")
    assert "semelhante a ROXOJ12 (Ferri) em carteira" in a["body"]
