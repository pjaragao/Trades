"""Testes para detecção e registro de sinais que voltaram ao preço originalmente operado."""
from datetime import datetime, timedelta, timezone
import pytest

from src.core import db
from src.core.config import now_iso
from src.services import alerts, price_returns, signals
from src.services.quotes import upsert_quote


def test_fmt_duration():
    assert price_returns.fmt_duration(30) == "menos de 1 min"
    assert price_returns.fmt_duration(120) == "2 min"
    assert price_returns.fmt_duration(3600) == "1h"
    assert price_returns.fmt_duration(3900) == "1h 5min"
    assert price_returns.fmt_duration(86400) == "1d"
    assert price_returns.fmt_duration(90000) == "1d 1h"


def test_is_price_drift_reason():
    assert price_returns.is_price_drift_reason("Preço já andou demais") is True
    assert price_returns.is_price_drift_reason("Preço andou") is True
    assert price_returns.is_price_drift_reason("Ficou longe") is True
    assert price_returns.is_price_drift_reason("Sem capital livre") is False
    assert price_returns.is_price_drift_reason("Não gosto do ativo") is False
    assert price_returns.is_price_drift_reason(None) is False


def test_price_return_detection_buy(tmp_db):
    # 1. Cria sinal de COMPRA de PETR4 a R$ 38,00
    now = datetime.now(timezone(timedelta(hours=-3)))
    decided_time = (now - timedelta(minutes=45)).isoformat(timespec="seconds")

    with db.transaction() as c:
        c.execute("""
            INSERT INTO signals(id, source, trades_id, trader, ticker, lado, asset_class, preco_entrada, status, first_seen_at)
            VALUES('sig-buy-1', 'tradingfloors', '101', 'Analista XP', 'PETR4', 'BUY', 'ACAO', 38.00, 'OPEN', ?)
        """, (decided_time,))
        c.execute("""
            INSERT INTO decisions(signal_id, status, reason, decided_at)
            VALUES('sig-buy-1', 'ignored', 'Preço já andou demais', ?)
        """, (decided_time,))
        upsert_quote(c, "PETR4", 39.50, source="test")

    # 2. Cotação ainda alta (R$ 39,50): não deve detectar retorno
    res = price_returns.check_price_returns()
    assert len(res) == 0

    # 3. Cotação recuou para R$ 37,90 (abaixo da entrada de 38,00): deve detectar!
    with db.transaction() as c:
        upsert_quote(c, "PETR4", 37.90, source="test")

    res = price_returns.check_price_returns()
    assert len(res) == 1
    r = res[0]
    assert r["signal_id"] == "sig-buy-1"
    assert r["ticker"] == "PETR4"
    assert r["side"] == "BUY"
    assert r["entry_price"] == 38.00
    assert r["returned_price"] == 37.90
    assert r["duration_seconds"] >= 45 * 60

    # 4. Verifica se gravou no histórico de signal_price_returns
    history = price_returns.list_price_returns()
    assert len(history) == 1
    h = history[0]
    assert h["signal_id"] == "sig-buy-1"
    assert h["ticker"] == "PETR4"
    assert h["entry_price"] == 38.00
    assert h["returned_price"] == 37.90
    assert "min" in h["duration_formatted"] or "h" in h["duration_formatted"]

    # 5. Verifica se gerou alerta
    all_alerts = alerts.list_alerts()
    al = next((a for a in all_alerts if a["signal_id"] == "sig-buy-1"), None)
    assert al is not None
    assert al["kind"] == "price_returned"
    assert "PETR4" in al["title"]
    assert "Demorou" in al["body"]


def test_price_return_detection_sell(tmp_db):
    # 1. Cria sinal de VENDA de VALE3 a R$ 60,00
    now = datetime.now(timezone(timedelta(hours=-3)))
    decided_time = (now - timedelta(hours=2)).isoformat(timespec="seconds")

    with db.transaction() as c:
        c.execute("""
            INSERT INTO signals(id, source, trades_id, trader, ticker, lado, asset_class, preco_entrada, status, first_seen_at)
            VALUES('sig-sell-1', 'tradingfloors', '102', 'Analista Genial', 'VALE3', 'SELL', 'ACAO', 60.00, 'OPEN', ?)
        """, (decided_time,))
        c.execute("""
            INSERT INTO decisions(signal_id, status, reason, decided_at)
            VALUES('sig-sell-1', 'ignored', 'Preço já andou demais', ?)
        """, (decided_time,))
        upsert_quote(c, "VALE3", 58.00, source="test")

    # 2. Cotação caiu para R$ 58,00 (longe da venda): não detecta
    assert len(price_returns.check_price_returns()) == 0

    # 3. Cotação subiu de volta para R$ 60,10 (favorável para venda de novo): deve detectar!
    with db.transaction() as c:
        upsert_quote(c, "VALE3", 60.10, source="test")

    res = price_returns.check_price_returns()
    assert len(res) == 1
    assert res[0]["signal_id"] == "sig-sell-1"
    assert res[0]["side"] == "SELL"
    assert res[0]["returned_price"] == 60.10


def test_ignore_reason_without_drift_is_not_detected(tmp_db):
    # Sinal ignorado por outro motivo (ex: sem capital) não deve disparar retorno ao preço
    with db.transaction() as c:
        c.execute("""
            INSERT INTO signals(id, source, trades_id, trader, ticker, lado, asset_class, preco_entrada, status, first_seen_at)
            VALUES('sig-other-1', 'tradingfloors', '103', 'Trader', 'ITUB4', 'BUY', 'ACAO', 30.00, 'OPEN', ?)
        """, (now_iso(),))
        c.execute("""
            INSERT INTO decisions(signal_id, status, reason, decided_at)
            VALUES('sig-other-1', 'ignored', 'Sem capital livre', ?)
        """, (now_iso(),))
        upsert_quote(c, "ITUB4", 29.50, source="test")

    assert len(price_returns.check_price_returns()) == 0
