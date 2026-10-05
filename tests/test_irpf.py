"""Conciliação completa pelas notas (a nota é a verdade), situação do mês (fechado x estimado) e simulação de encerrar tudo."""
from datetime import datetime

import pytest

from src.core import db
from src.core.market_hours import BRT
from src.services import brokerage_notes as bn
from src.services import irpf, journal, portfolio
from src.services.tax import monthly_tax
from tests.test_notes import XP_PAGE, make_pdf

NATU_LINE = "1-BOVESPA C OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 2.600 0,39 1.014,00 D"
PETR_LINE = "1-BOVESPA V VISTA PETROBRAS PN N2 100 38,50 3.850,00 C"


def xp_note(lines=None, date_br="05/10/2026", number="75104212"):
    text = XP_PAGE.replace("75104212 1 05/10/2026", f"{number} 1 {date_br}")
    body = "\n".join(lines if lines is not None else [NATU_LINE, PETR_LINE])
    return text.replace(NATU_LINE + "\n" + PETR_LINE, body)


def add(ticker, side, qty, price, when, fees=0.0, **kw):
    return journal.add_execution({"ticker": ticker, "side": side, "quantity": qty, "price": price, "fees": fees,
                                  "executed_at": when, **kw}, allow_short=True)


def preview(text, **kw):
    return bn.build_preview([("nota.pdf", make_pdf([text]))], **kw)


def groups(prev, i=0):
    return {g["ticker"]: g for g in prev["notes"][i]["groups"]}


def test_quantity_mismatch_replaces_with_note_and_undo_restores(tmp_db):
    a = add("NATUK800", "BUY", 1000, 0.40, "2026-10-05T11:00:00-03:00")
    b = add("NATUK800", "BUY", 1500, 0.41, "2026-10-05T11:20:00-03:00")
    prev = preview(xp_note([NATU_LINE]))
    g = groups(prev)["NATUK800"]
    assert g["action"] == "replace" and "quantidade 2.500 → 2.600" in g["match_note"]
    res = bn.apply_preview(prev)
    assert res["replaced"] == 1 and not res["errors"]
    rows = journal.list_executions(ticker="NATUK800")
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == a["id"] and r["quantity"] == 2600 and r["price"] == pytest.approx(0.39) and r["fees_source"] == "note"
    assert r["fees"] == pytest.approx(1.49) and r["executed_at"].startswith("2026-10-05T11:00")
    # desfazer devolve as duas execuções como eram
    bn.delete_note(bn.list_notes()[0]["id"])
    back = {x["id"]: x for x in journal.list_executions(ticker="NATUK800")}
    assert set(back) == {a["id"], b["id"]} and back[b["id"]]["price"] == pytest.approx(0.41) and back[a["id"]]["quantity"] == 1000


def test_subset_matches_and_extra_can_be_deleted(tmp_db):
    add("NATUK800", "BUY", 1000, 0.39, "2026-10-05T11:00:00-03:00")
    add("NATUK800", "BUY", 1600, 0.39, "2026-10-05T11:05:00-03:00")
    extra = add("VALE3", "BUY", 100, 60.0, "2026-10-05T12:00:00-03:00")
    prev = preview(xp_note([NATU_LINE]))
    note = prev["notes"][0]
    g = groups(prev)["NATUK800"]
    assert g["action"] == "update" and len(g["matches"]) == 2
    assert [x["id"] for x in note["extras"]] == [extra["id"]]
    note["extras"][0]["action"] = "delete"
    res = bn.apply_preview(prev)
    assert res["updated"] == 1 and res["deleted"] == 1
    assert journal.list_executions(ticker="VALE3") == []
    natu = journal.list_executions(ticker="NATUK800")
    assert sum(x["fees"] for x in natu) == pytest.approx(1.49) and all(x["note_id"] for x in natu)
    bn.delete_note(bn.list_notes()[0]["id"])
    assert len(journal.list_executions(ticker="VALE3")) == 1


def test_execution_registered_on_wrong_day_gets_note_date(tmp_db):
    e = add("NATUK800", "BUY", 2600, 0.40, "2026-10-06T11:30:00-03:00")
    prev = preview(xp_note([NATU_LINE]))
    g = groups(prev)["NATUK800"]
    assert g["action"] == "update" and "data 06/10 → 05/10" in g["match_note"]
    bn.apply_preview(prev)
    r = journal.list_executions(ticker="NATUK800")[0]
    assert r["id"] == e["id"] and r["executed_at"] == "2026-10-05T11:30:00-03:00" and r["price"] == pytest.approx(0.39)


def test_each_execution_gets_its_own_line_price(tmp_db):
    add("NATUK800", "BUY", 1300, 0.385, "2026-10-05T11:00:00-03:00")
    add("NATUK800", "BUY", 1300, 0.395, "2026-10-05T11:10:00-03:00")
    lines = ["1-BOVESPA C OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 1.300 0,38 494,00 D",
             "1-BOVESPA C OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 1.300 0,40 520,00 D"]
    prev = preview(xp_note(lines))
    assert groups(prev)["NATUK800"]["action"] == "update"
    bn.apply_preview(prev)
    prices = sorted(x["price"] for x in journal.list_executions(ticker="NATUK800"))
    assert prices == [pytest.approx(0.38), pytest.approx(0.40)]


def test_month_closes_only_when_every_trading_day_has_a_note(tmp_db):
    add("NATUK800", "BUY", 2600, 0.39, "2026-10-05T11:00:00-03:00")
    add("NATUK800", "SELL", 2600, 0.50, "2026-10-09T11:00:00-03:00")
    bn.apply_preview(preview(xp_note([NATU_LINE])))
    rep = irpf.report()
    oct_ = next(m for m in rep["months"] if m["month"] == "2026-10")
    assert oct_["status"] == "estimado" and [d["date"] for d in oct_["missing_days"]] == ["2026-10-09"]
    sell = "1-BOVESPA V OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 2.600 0,50 1.300,00 C"
    bn.apply_preview(preview(xp_note([sell], date_br="09/10/2026", number="75104999")))
    oct_ = next(m for m in irpf.report()["months"] if m["month"] == "2026-10")
    assert oct_["status"] == "fechado" and oct_["irrf_source"] == "nota" and oct_["missing_days"] == []
    assert irpf.report()["coverage"]["days_covered"] == 2


def test_irrf_per_day_note_or_estimate_and_carry():
    ev = lambda d, kind, pnl, sale: {"date": d, "kind": kind, "pnl": pnl, "sale_gross": sale, "asset_class": "OPCAO", "ticker": "X"}
    events = [ev("2026-09-10", "swing", -500.0, 100000.0), ev("2026-09-11", "swing", 10.0, 100000.0), ev("2026-10-10", "swing", 1000.0, 3000.0)]
    rows = {r["month"]: r for r in monthly_tax(events, irrf_days={"2026-09-10": {"swing": 1.0, "day": None}})}
    sep, oct_ = rows["2026-09"], rows["2026-10"]
    assert sep["irrf_estimate"] == pytest.approx(1.0 + 100000 * 0.00005) and sep["irrf_source"] == "parcial"
    assert sep["tax_due"] == 0 and sep["irrf_carry"] == pytest.approx(6.0)  # sem IR no mês: IRRF fica de crédito
    assert oct_["irrf_used"] == pytest.approx(6.0 + 3000 * 0.00005)


def test_simulate_close_all_shows_tax_and_lost_exemption(tmp_db):
    add("PETR4", "BUY", 1000, 20.0, "2026-10-01T11:00:00-03:00")
    portfolio.set_manual_quote("PETR4", 25.0)
    at = datetime(2026, 10, 20, 12, 0, tzinfo=BRT)
    sim = irpf.simulate_close_all(at=at)
    it = sim["positions"][0]
    assert it["ticker"] == "PETR4" and it["side"] == "SELL" and it["price"] == 25.0 and it["kind"] == "swing"
    assert sim["after"]["stock_sales"] == pytest.approx(25000.0) and not sim["after"]["stock_exempt"]
    expected = it["pnl"] * 0.15 - 25000 * 0.00005
    assert sim["additional_tax"] == pytest.approx(expected, abs=0.02) and sim["before"]["tax_due"] == 0
    assert any("deixa de ser isento" in w["text"] for w in sim["warnings"])
    # comprado no próprio dia: encerrar hoje é day trade (20%)
    add("VALE3", "BUY", 10, 60.0, "2026-10-20T10:30:00-03:00")
    portfolio.set_manual_quote("VALE3", 63.0)
    sim = irpf.simulate_close_all(at=at)
    vale = next(i for i in sim["positions"] if i["ticker"] == "VALE3")
    assert vale["kind"] == "day" and any("day trade" in w["text"] for w in sim["warnings"])
    assert sim["after"]["day_trade_pnl"] == pytest.approx(vale["pnl"])


def test_ir_api(tmp_db):
    from web.app import create_app

    client = create_app(start_monitor=False, db_path=db.db_path()).test_client()
    add("PETR4", "BUY", 100, 20.0, "2026-10-01T11:00:00-03:00")
    rep = client.get("/api/ir").get_json()
    assert "months" in rep and "years" in rep and rep["coverage"]["days_total"] == 1
    sim = client.get("/api/ir/simulate-close").get_json()
    assert sim["missing_quotes"] == ["PETR4"] and sim["estimated"]
