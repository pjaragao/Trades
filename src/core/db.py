"""
Banco único do Copiloto (database/app.db) com migrações versionadas (PRAGMA user_version).

Tabelas:
- signals     : todo sinal do TradingFloors (abertos + histórico), já deduplicado.
                `id` é o id canônico; `trades_id` aponta a linha de `trades`; `linked_ids` guarda
                os demais ids brutos absorvidos (ex.: linhas de `opcoes_trades`)
- decisions   : minha decisão por sinal (executado / ignorado / adiado)
- executions  : o que eu executei no Home Broker (fonte da verdade para posições e P&L)
- alerts      : novo sinal, saída pendente, stop/alvo, avisos do sistema
- quotes      : último preço conhecido por ativo (MT5 ao vivo, brapi, TradingFloors ou manual)
- settings    : preferências do usuário (JSON por seção)
- kv          : estado interno (baseline do monitor, última sincronização etc.)
- orders / order_fills : ordens enviadas ao MT5 ou à conta simulada (Fase 6) e seus preenchimentos
- automation_log       : cada decisão da automação (enviou / bloqueou e por quê)
- notes                : notas de corretagem importadas (custos reais, IRRF)

`executions.account` separa a conta real da simulada ('paper').
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from src.core.config import DEFAULT_DB_PATH

_db_path: Path = DEFAULT_DB_PATH
_write_lock = threading.RLock()

MIGRATIONS = [
    # v1 — modelo do fluxo manual
    """
    CREATE TABLE IF NOT EXISTS signals (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        trades_id TEXT,
        linked_ids TEXT NOT NULL DEFAULT '[]',
        produto TEXT,
        tipo_ativo TEXT,
        asset_class TEXT NOT NULL DEFAULT 'OUTRO',
        ticker TEXT NOT NULL,
        underlying TEXT,
        opcao_tipo TEXT,
        strike REAL,
        expiration TEXT,
        trader TEXT NOT NULL,
        lado TEXT NOT NULL,
        quantidade REAL,
        preco_entrada REAL,
        stop_loss REAL,
        take_profit REAL,
        preco_atual REAL,
        preco_atual_at TEXT,
        preco_saida REAL,
        pnl_realizado REAL,
        pnl_pontos REAL,
        timestamp_entrada TEXT,
        timestamp_saida TEXT,
        status TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        closed_seen_at TEXT,
        updated_at TEXT,
        is_baseline INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
    CREATE INDEX IF NOT EXISTS idx_signals_trader ON signals(trader);
    CREATE INDEX IF NOT EXISTS idx_signals_entry ON signals(timestamp_entrada);
    CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
    CREATE INDEX IF NOT EXISTS idx_signals_trades_id ON signals(trades_id);

    CREATE TABLE IF NOT EXISTS decisions (
        signal_id TEXT PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK (status IN ('executed', 'ignored', 'snoozed')),
        reason TEXT,
        remind_at TEXT,
        decided_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT REFERENCES signals(id) ON DELETE SET NULL,
        ticker TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity REAL NOT NULL CHECK (quantity > 0),
        price REAL NOT NULL CHECK (price >= 0),
        fees REAL NOT NULL DEFAULT 0 CHECK (fees >= 0),
        executed_at TEXT NOT NULL,
        asset_class TEXT NOT NULL DEFAULT 'OUTRO',
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_exec_ticker ON executions(ticker, executed_at);
    CREATE INDEX IF NOT EXISTS idx_exec_signal ON executions(signal_id);

    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        signal_id TEXT,
        ticker TEXT,
        title TEXT NOT NULL,
        body TEXT,
        severity TEXT NOT NULL DEFAULT 'info',
        created_at TEXT NOT NULL,
        read_at TEXT,
        notified_at TEXT,
        dedup_key TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_alerts_unread ON alerts(read_at);

    CREATE TABLE IF NOT EXISTS quotes (
        ticker TEXT PRIMARY KEY,
        price REAL NOT NULL,
        source TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS kv (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # v2 — Fase 6 (ordens via MT5/simulação), contas real/paper e notas de corretagem
    """
    ALTER TABLE executions ADD COLUMN account TEXT NOT NULL DEFAULT 'real';
    ALTER TABLE executions ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    ALTER TABLE executions ADD COLUMN order_id INTEGER;
    ALTER TABLE executions ADD COLUMN note_id INTEGER;
    ALTER TABLE executions ADD COLUMN fees_source TEXT NOT NULL DEFAULT 'manual';
    CREATE INDEX IF NOT EXISTS idx_exec_account ON executions(account, executed_at);

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT NOT NULL CHECK (account IN ('real', 'paper')),
        broker TEXT NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('manual', 'auto')),
        purpose TEXT NOT NULL CHECK (purpose IN ('entry', 'exit', 'other')),
        signal_id TEXT,
        cycle_id TEXT,
        ticker TEXT NOT NULL,
        asset_class TEXT NOT NULL DEFAULT 'OUTRO',
        side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity REAL NOT NULL CHECK (quantity > 0),
        order_type TEXT NOT NULL CHECK (order_type IN ('limit', 'market')),
        limit_price REAL,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        filled_qty REAL NOT NULL DEFAULT 0,
        avg_fill_price REAL,
        message TEXT,
        risk_json TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        updated_at TEXT,
        closed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_orders_signal ON orders(signal_id);

    CREATE TABLE IF NOT EXISTS order_fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        broker_fill_id TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        fees REAL NOT NULL DEFAULT 0,
        filled_at TEXT NOT NULL,
        execution_id INTEGER,
        UNIQUE (order_id, broker_fill_id)
    );

    CREATE TABLE IF NOT EXISTS automation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        account TEXT NOT NULL,
        action TEXT NOT NULL,
        decision TEXT NOT NULL,
        signal_id TEXT,
        order_id INTEGER,
        ticker TEXT,
        reason TEXT
    );

    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        broker TEXT NOT NULL,
        number TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        settlement_date TEXT,
        file_name TEXT,
        file_hash TEXT,
        gross_value REAL,
        net_value REAL,
        total_costs REAL,
        brokerage REAL,
        b3_fees REAL,
        taxes REAL,
        irrf REAL,
        fees_json TEXT,
        trades_json TEXT,
        imported_at TEXT NOT NULL,
        UNIQUE (broker, number, trade_date)
    );
    """,
    # v3 — cotações ao vivo (MT5): bid/ask, último negócio, horário do negócio e variação do dia
    """
    ALTER TABLE quotes ADD COLUMN bid REAL;
    ALTER TABLE quotes ADD COLUMN ask REAL;
    ALTER TABLE quotes ADD COLUMN last REAL;
    ALTER TABLE quotes ADD COLUMN quote_time TEXT;
    ALTER TABLE quotes ADD COLUMN change_pct REAL;
    """,
    # v4 — conciliação completa pelas notas (desfazer restaura o histórico) e IRRF de day trade da nota
    """
    ALTER TABLE notes ADD COLUMN undo_json TEXT;
    ALTER TABLE notes ADD COLUMN irrf_day REAL;
    """,
]


def configure(path) -> None:
    """Aponta o módulo para outro arquivo (testes) e aplica as migrações."""
    global _db_path
    _db_path = Path(path)
    init_db()


def db_path() -> Path:
    return _db_path


def connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def connection(conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    c = connect()
    try:
        yield c
    finally:
        c.close()


@contextmanager
def transaction(conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
    """Transação de escrita serializada. Se receber uma conexão, apenas a reutiliza."""
    if conn is not None:
        yield conn
        return
    with _write_lock:
        c = connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()


def init_db() -> None:
    with _write_lock:
        c = connect()
        try:
            c.execute("PRAGMA journal_mode = WAL")
            version = c.execute("PRAGMA user_version").fetchone()[0]
            for target, script in enumerate(MIGRATIONS, start=1):
                if version < target:
                    c.executescript("BEGIN;" + script + f"PRAGMA user_version = {target}; COMMIT;")
        finally:
            c.close()


def kv_get(key: str, default: Optional[str] = None, conn=None) -> Optional[str]:
    with connection(conn) as c:
        row = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: Optional[str], conn=None) -> None:
    with transaction(conn) as c:
        c.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
