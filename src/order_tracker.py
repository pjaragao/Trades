import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

class OrderTracker:
    """
    Rastreamento local em SQLite para sincronização de ordens entre TradingFloors e MT5.
    Garante idempotência, evita duplicidades e monitora encerramentos.
    """

    def __init__(self, db_path: str = "database/trades_tracker.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_trades (
                    trade_id TEXT PRIMARY KEY,
                    source_table TEXT,
                    produto TEXT,
                    ticker TEXT,
                    trader_nome TEXT,
                    lado TEXT,
                    preco_entrada_sugerido REAL,
                    preco_entrada_executado REAL,
                    quantidade_sugerida REAL,
                    quantidade_executada REAL,
                    mt5_ticket INTEGER,
                    status TEXT,
                    timestamp_entrada TEXT,
                    timestamp_saida TEXT,
                    preco_saida REAL,
                    pnl_realizado REAL,
                    observacoes TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()

    def is_trade_processed(self, trade_id: str) -> bool:
        """Verifica se o sinal já foi registrado no banco local."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM synced_trades WHERE trade_id = ?", (trade_id,))
            return cursor.fetchone() is not None

    def record_entry(
        self,
        trade_id: str,
        source_table: str,
        produto: str,
        ticker: str,
        trader_nome: str,
        lado: str,
        preco_entrada_sugerido: float,
        preco_entrada_executado: float = None,
        quantidade_sugerida: float = 100.0,
        quantidade_executada: float = None,
        mt5_ticket: int = None,
        timestamp_entrada: str = None,
        status: str = "OPEN",
        observacoes: str = ""
    ) -> bool:
        """Registra a abertura de uma nova posição executada."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO synced_trades (
                    trade_id, source_table, produto, ticker, trader_nome, lado,
                    preco_entrada_sugerido, preco_entrada_executado,
                    quantidade_sugerida, quantidade_executada, mt5_ticket,
                    status, timestamp_entrada, observacoes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, source_table, produto, ticker, trader_nome, lado,
                preco_entrada_sugerido, preco_entrada_executado,
                quantidade_sugerida, quantidade_executada, mt5_ticket,
                status, timestamp_entrada, observacoes, now_iso, now_iso
            ))
            conn.commit()
            return True

    def mark_skipped(self, trade_id: str, ticker: str, trader_nome: str, produto: str, reason: str):
        """Registra um trade ignorado pelos filtros para não reprocessar no loop."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO synced_trades (
                    trade_id, produto, ticker, trader_nome, status, observacoes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'SKIPPED', ?, ?, ?)
            """, (trade_id, produto, ticker, trader_nome, reason, now_iso, now_iso))
            conn.commit()

    def record_exit(
        self,
        trade_id: str,
        preco_saida: float,
        timestamp_saida: Optional[str] = None,
        pnl_realizado: Optional[float] = None
    ) -> bool:
        """Atualiza a posição com os dados de encerramento."""
        now_iso = datetime.now(timezone.utc).isoformat()
        ts_saida = timestamp_saida or now_iso

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE synced_trades
                SET status = 'CLOSED',
                    preco_saida = ?,
                    timestamp_saida = ?,
                    pnl_realizado = ?,
                    updated_at = ?
                WHERE trade_id = ?
            """, (preco_saida, ts_saida, pnl_realizado, now_iso, trade_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_open_synced_trades(self) -> List[Dict[str, Any]]:
        """Retorna todas as posições atualmente abertas no rastreador local."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM synced_trades WHERE status = 'OPEN'")
            return [dict(row) for row in cursor.fetchall()]

    def get_trade_by_id(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Busca um registro pelo UUID do Supabase."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM synced_trades WHERE trade_id = ?", (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_tracked(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna histórico completo ordenado por data de criação."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM synced_trades ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
