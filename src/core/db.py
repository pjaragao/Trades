"""
Banco único do Copiloto (database/app.db) com migrações versionadas (PRAGMA user_version).

Tabelas:
- signals     : todo sinal do TradingFloors (abertos + histórico), já deduplicado.
                `id` é o id canônico; `trades_id` aponta a linha de `trades`; `linked_ids` guarda
                os demais ids brutos absorvidos (ex.: linhas de `opcoes_trades`)
- decisions   : minha decisão por sinal (executado / ignorado / adiado)
- executions  : o que eu executei no Home Broker (fonte da verdade para posições e P&L)
- alerts      : novo sinal, saída pendente, stop/alvo, avisos do sistema
- quotes      : último preço conhecido por ativo (TradingFloors ou manual)
- settings    : preferências do usuário (JSON por seção)
- kv          : estado interno (baseline do monitor, última sincronização etc.)
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
