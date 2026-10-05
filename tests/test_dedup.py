"""Deduplicação única: `trades` é canônica, `opcoes_trades` só enriquece."""
from src.core import db
from src.integrations.tradingfloors import merge_rows
from src.services.signals import upsert_signals
from tests.conftest import opcao_row, trade_row


def test_opcao_linked_by_opcao_id_enriches_trade():
    t = trade_row("t1", "NATUK800", opcao_id="o1", preco=0.38)
    o = opcao_row("o1", "NATUK800", preco=0.38, atual=0.54, strike=8.0)
    merged = merge_rows([t], [o])
    assert len(merged) == 1
    s = merged[0]
    assert s["id"] == "t1" and s["trades_id"] == "t1"
    assert s["linked_ids"] == ["o1"]
    assert s["preco_atual"] == 0.54 and s["strike"] == 8.0 and s["opcao_tipo"] == "CALL"
    assert "Opções" in s["produto"]
    assert s["underlying"] == "NATU3"
    assert s["expiration"] == "2026-11-19"  # 3ª sexta (20/11) é feriado -> recua


def test_duplicate_opcoes_rows_collapse_into_one_signal():
    # Mesmo sinal lançado duas vezes em opcoes_trades (13:13 e 13:15) e uma vez em trades
    t = trade_row("t1", "BBASJ23", preco=0.63, ts="2026-09-28T13:15:00+00:00", opcao_id="o2")
    o1 = opcao_row("o1", "BBASJ23", preco=0.63, ts="2026-09-28T13:13:00+00:00")
    o2 = opcao_row("o2", "BBASJ23", preco=0.63, ts="2026-09-28T13:15:00+00:00")
    merged = merge_rows([t], [o1, o2])
    assert len(merged) == 1
    assert sorted(merged[0]["linked_ids"]) == ["o1", "o2"]


def test_same_day_scalps_in_trades_are_not_merged():
    a = trade_row("a", "WINFUT", trader="Brondi", preco=188000, tipo="Futuros (B3)", produto="Trading Floor", ts="2026-09-09T03:00:00+00:00")
    b = trade_row("b", "WINFUT", trader="Brondi", preco=188500, tipo="Futuros (B3)", produto="Trading Floor", ts="2026-09-09T03:00:00+00:00")
    assert len(merge_rows([a, b], [])) == 2


def test_unmatched_opcao_becomes_its_own_signal():
    merged = merge_rows([], [opcao_row("o9", "PETRV480", trader="Ferri", preco=1.25, atual=0.22)])
    assert len(merged) == 1
    s = merged[0]
    assert s["source"] == "opcoes_trades" and s["trades_id"] is None
    assert s["opcao_tipo"] == "CALL"  # informado pela linha (o ticker diria PUT)
    assert s["asset_class"] == "OPCAO"


def test_stale_opcao_row_does_not_create_phantom_signal(tmp_db):
    # Histórico: Sanita encerrou MGLUJ584 em trades, mas opcoes_trades ainda mostra aberta
    closed = trade_row("t1", "MGLUJ584", preco=0.6, status="CLOSED", saida=1.26,
                       ts="2026-09-08T18:32:00+00:00", ts_saida="2026-09-28T14:34:00+00:00")
    stale = opcao_row("o1", "MGLUJ584", preco=0.6, atual=1.8, ts="2026-09-08T18:32:00+00:00")
    with db.transaction() as c:
        upsert_signals(c, merge_rows([closed], []), baseline=True)
        # Poll seguinte só traz os abertos: a linha velha de opcoes_trades não tem par em `trades`
        res = upsert_signals(c, merge_rows([], [stale]))
        rows = c.execute("SELECT id, status, preco_atual FROM signals").fetchall()
    assert res["new"] == []
    assert len(rows) == 1
    assert rows[0]["status"] == "CLOSED" and rows[0]["preco_atual"] == 1.8


def test_opcao_first_then_trade_row_is_linked_not_duplicated(tmp_db):
    o = opcao_row("o1", "ASAIJ107", trader="Artur Horta", preco=0.54, ts="2026-09-30T15:38:00+00:00")
    t = trade_row("t1", "ASAIJ107", trader="Artur Horta", preco=0.54, ts="2026-09-30T15:38:00+00:00")
    with db.transaction() as c:
        r1 = upsert_signals(c, merge_rows([], [o]))
        r2 = upsert_signals(c, merge_rows([t], []))
        rows = c.execute("SELECT id, trades_id, linked_ids FROM signals").fetchall()
    assert r1["new"] == ["o1"] and r2["new"] == []
    assert len(rows) == 1
    assert rows[0]["id"] == "o1" and rows[0]["trades_id"] == "t1"


def test_closure_is_detected_as_transition(tmp_db):
    t_open = trade_row("t1", "AZZAK185", trader="Ferri", preco=2.5)
    t_closed = dict(t_open, status="CLOSED", preco_saida=3.1, timestamp_saida="2026-10-05T15:00:00+00:00")
    with db.transaction() as c:
        upsert_signals(c, merge_rows([t_open], []))
        res = upsert_signals(c, merge_rows([t_closed], []))
    assert res["closed"] == ["t1"]
