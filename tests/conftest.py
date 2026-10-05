import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db  # noqa: E402
from src.services import performance  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    from src.services import legacy_import

    monkeypatch.setattr(legacy_import, "LEGACY_CACHE", tmp_path / "sem_cache_antigo.db")
    db.configure(tmp_path / "app.db")
    performance.invalidate_cache()
    yield tmp_path / "app.db"
    performance.invalidate_cache()


def trade_row(id, ticker, trader="Sanita", lado="BUY", preco=1.0, status="OPEN", ts="2026-10-02T14:00:00+00:00",
              tipo="OPCOES", produto="Desafio Eleições", opcao_id=None, saida=None, ts_saida=None, qtd=1000.0, **extra):
    row = {
        "id": id, "ticker": ticker, "trader_nome": trader, "lado": lado, "preco_entrada": preco, "status": status,
        "timestamp_entrada": ts, "tipo_ativo": tipo, "produto": produto, "opcao_id": opcao_id, "preco_saida": saida,
        "timestamp_saida": ts_saida, "quantidade": qtd, "stop_loss": None, "take_profit": None, "pnl_realizado": None,
        "pnl_pontos": None, "updated_at": ts,
    }
    row.update(extra)
    return row


def opcao_row(id, ticker, trader="Sanita", lado="BUY", preco=1.0, atual=1.1, status="OPEN", ts="2026-10-02T14:00:00+00:00", strike=10.0, qtd=1000.0):
    return {
        "id": id, "ticker": ticker, "trader_nome": trader, "lado": lado, "preco_entrada": preco, "preco_atual": atual,
        "status": status, "timestamp_entrada": ts, "opcao_tipo": "CALL", "strike": strike, "produto": "Opções",
        "quantidade": qtd, "preco_saida": None, "timestamp_saida": None,
    }


class FakeAPI:
    """Imita o TradingFloorsAPI com tabelas em memória."""

    configured = True

    def __init__(self, trades=None, opcoes=None):
        self.trades = list(trades or [])
        self.opcoes = list(opcoes or [])

    def fetch_all(self):
        return list(self.trades), list(self.opcoes)

    def fetch_open(self):
        return [t for t in self.trades if t["status"] == "OPEN"], [o for o in self.opcoes if o["status"] == "OPEN"]

    def fetch_trades_updated_since(self, iso):
        return [t for t in self.trades if (t.get("updated_at") or "") >= iso]

    def fetch_trades_by_ids(self, ids):
        ids = set(ids)
        return [t for t in self.trades if t["id"] in ids]

    def fetch_recent_closed(self, ticker, trader_raw_hint=None, limit=20):
        return [t for t in self.trades if t["ticker"] == ticker and t["status"] == "CLOSED"]


@pytest.fixture()
def fake_api():
    return FakeAPI()
