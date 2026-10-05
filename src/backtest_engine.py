import os
import math
import sqlite3
import requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from src.utils import normalize_trader_name

class BacktestEngine:
    """
    Motor quantitativo de Backtest histórico com base nos trades reais
    registrados no Supabase da TradingFloors.
    """

    def __init__(self, supabase_url: str, supabase_anon_key: str, token: Optional[str] = None, cache_db: str = "database/backtest_cache.db"):
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_anon_key = supabase_anon_key
        self.token = token
        self.cache_db = cache_db
        self._init_cache_db()

    def _init_cache_db(self):
        os.makedirs(os.path.dirname(self.cache_db), exist_ok=True)
        with sqlite3.connect(self.cache_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS historical_trades (
                    id TEXT PRIMARY KEY,
                    source_table TEXT,
                    produto TEXT,
                    tipo_ativo TEXT,
                    ticker TEXT,
                    trader_nome TEXT,
                    lado TEXT,
                    quantidade REAL,
                    preco_entrada REAL,
                    preco_saida REAL,
                    pnl_realizado REAL,
                    pnl_pontos REAL,
                    timestamp_entrada TEXT,
                    timestamp_saida TEXT,
                    status TEXT,
                    created_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_status ON historical_trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_produto ON historical_trades(produto)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_trader ON historical_trades(trader_nome)")
            conn.commit()

    def sync_historical_data(self, token: Optional[str] = None) -> int:
        """
        Baixa todas as operações históricas do Supabase e salva no cache SQLite local
        para que os backtests rodem instantaneamente sem requisições de rede repetidas.
        """
        auth_token = token or self.token
        headers = {
            "apikey": self.supabase_anon_key,
            "Content-Type": "application/json"
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        total_synced = 0
        step = 1000

        # 1. Tabela 'trades'
        offset = 0
        while True:
            url = f"{self.supabase_url}/rest/v1/trades?select=*&order=timestamp_entrada.asc&offset={offset}&limit={step}"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break

            with sqlite3.connect(self.cache_db) as conn:
                cursor = conn.cursor()
                for row in data:
                    cursor.execute("""
                        INSERT OR REPLACE INTO historical_trades (
                            id, source_table, produto, tipo_ativo, ticker, trader_nome,
                            lado, quantidade, preco_entrada, preco_saida, pnl_realizado,
                            pnl_pontos, timestamp_entrada, timestamp_saida, status, created_at
                        ) VALUES (?, 'trades', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("id"),
                        row.get("produto") or "Trading Floor",
                        row.get("tipo_ativo"),
                        row.get("ticker"),
                        normalize_trader_name(row.get("trader_nome")),
                        row.get("lado") or "BUY",
                        float(row.get("quantidade") or 0),
                        float(row.get("preco_entrada") or 0),
                        float(row.get("preco_saida") or 0) if row.get("preco_saida") is not None else None,
                        float(row.get("pnl_realizado") or 0) if row.get("pnl_realizado") is not None else None,
                        float(row.get("pnl_pontos") or 0) if row.get("pnl_pontos") is not None else None,
                        row.get("timestamp_entrada"),
                        row.get("timestamp_saida"),
                        row.get("status"),
                        datetime.now(timezone.utc).isoformat()
                    ))
                conn.commit()

            total_synced += len(data)
            if len(data) < step:
                break
            offset += step

        # 2. Tabela 'opcoes_trades'
        offset = 0
        while True:
            url = f"{self.supabase_url}/rest/v1/opcoes_trades?select=*&order=timestamp_entrada.asc&offset={offset}&limit={step}"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break

            with sqlite3.connect(self.cache_db) as conn:
                cursor = conn.cursor()
                for row in data:
                    t_ticker = row.get("ticker")
                    t_trader = normalize_trader_name(row.get("trader_nome"))
                    t_pe = round(float(row.get("preco_entrada") or 0), 4)
                    t_ts = str(row.get("timestamp_entrada") or "")[:16]

                    # Verifica se já existe um trade equivalente vindo de 'trades'
                    cursor.execute("""
                        SELECT id, pnl_realizado, preco_saida, produto FROM historical_trades
                        WHERE ticker = ? AND trader_nome = ? AND round(preco_entrada, 4) = ? AND substr(timestamp_entrada, 1, 16) = ?
                    """, (t_ticker, t_trader, t_pe, t_ts))
                    existing = cursor.fetchone()

                    if existing:
                        ex_id, ex_pnl, ex_saida, ex_prod = existing
                        new_pnl = float(row.get("pnl_realizado")) if row.get("pnl_realizado") is not None else ex_pnl
                        new_saida = float(row.get("preco_saida")) if row.get("preco_saida") is not None else ex_saida
                        new_prod = "Desafio Eleições / Opções" if "Desafio" in str(ex_prod) else "Opções"
                        cursor.execute("""
                            UPDATE historical_trades 
                            SET pnl_realizado = ?, preco_saida = ?, produto = ?
                            WHERE id = ?
                        """, (new_pnl, new_saida, new_prod, ex_id))
                    else:
                        cursor.execute("""
                            INSERT OR IGNORE INTO historical_trades (
                                id, source_table, produto, tipo_ativo, ticker, trader_nome,
                                lado, quantidade, preco_entrada, preco_saida, pnl_realizado,
                                pnl_pontos, timestamp_entrada, timestamp_saida, status, created_at
                            ) VALUES (?, 'opcoes_trades', 'Opções', 'OPCOES', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get("id"),
                            t_ticker,
                            t_trader,
                            row.get("lado") or "BUY",
                            float(row.get("quantidade") or 0),
                            float(row.get("preco_entrada") or 0),
                            float(row.get("preco_saida") or 0) if row.get("preco_saida") is not None else None,
                            float(row.get("pnl_realizado") or 0) if row.get("pnl_realizado") is not None else None,
                            float(row.get("pnl_pontos") or 0) if row.get("pnl_pontos") is not None else None,
                            row.get("timestamp_entrada"),
                            row.get("timestamp_saida"),
                            row.get("status"),
                            datetime.now(timezone.utc).isoformat()
                        ))
                conn.commit()

            total_synced += len(data)
            if len(data) < step:
                break
            offset += step

        return total_synced

    def get_cached_count(self) -> int:
        with sqlite3.connect(self.cache_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM historical_trades")
            return cursor.fetchone()[0]

    def get_filter_options(self) -> Dict[str, List[str]]:
        """Retorna lista de produtos e traders disponíveis no histórico devidamente normalizados e sem duplicatas."""
        with sqlite3.connect(self.cache_db) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT produto FROM historical_trades WHERE produto IS NOT NULL ORDER BY produto")
            produtos = [r["produto"] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT trader_nome FROM historical_trades WHERE trader_nome IS NOT NULL")
            raw_traders = [r["trader_nome"] for r in cursor.fetchall()]
            traders_set = {normalize_trader_name(tr) for tr in raw_traders if tr and tr.lower() != "desconhecido"}
            traders = sorted(list(traders_set))

        return {"produtos": produtos, "traders": traders}

    def run_backtest(
        self,
        initial_equity: float = 10000.0,
        sizing_mode: str = "fixed_capital",
        fixed_capital: float = 1000.0,
        fixed_quantity: int = 100,
        product: str = "all",
        trader: str = "all",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executa a simulação completa de backtest com base nos parâmetros solicitados.
        """
        # Monta query SQL com filtros
        query = ["SELECT * FROM historical_trades WHERE status = 'CLOSED' AND preco_saida IS NOT NULL"]
        params = []

        if product != "all" and product:
            if product == "Desafio Eleições":
                query.append("AND (produto = ? OR tipo_ativo = 'OPCOES')")
                params.append(product)
            else:
                query.append("AND produto = ?")
                params.append(product)

        if trader != "all" and trader:
            norm_target = normalize_trader_name(trader).lower()
            query.append("AND LOWER(trader_nome) = ?")
            params.append(norm_target)

        if date_from:
            query.append("AND timestamp_entrada >= ?")
            params.append(date_from)

        if date_to:
            query.append("AND timestamp_entrada <= ?")
            params.append(date_to + "T23:59:59")

        query.append("ORDER BY timestamp_entrada ASC")
        sql = " ".join(query)

        trades_list: List[Dict[str, Any]] = []
        with sqlite3.connect(self.cache_db) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                trades_list.append(dict(row))

        # Variáveis de acompanhamento
        current_equity = initial_equity
        peak_equity = initial_equity
        max_drawdown_val = 0.0
        max_drawdown_pct = 0.0

        equity_curve: List[Dict[str, Any]] = [{
            "date": "Início",
            "equity": initial_equity,
            "pnl": 0.0,
            "ticker": "START",
            "drawdown": 0.0
        }]

        simulated_trades: List[Dict[str, Any]] = []
        trader_stats: Dict[str, Dict[str, Any]] = {}
        monthly_stats: Dict[str, float] = {}

        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        gross_profit = 0.0
        gross_loss = 0.0

        for t in trades_list:
            preco_ent = float(t.get("preco_entrada") or 0)
            preco_sai = float(t.get("preco_saida") or 0)
            orig_qtd = float(t.get("quantidade") or 1)
            lado = str(t.get("lado") or "BUY").upper()
            ticker = t.get("ticker", "")
            trader_nome = normalize_trader_name(t.get("trader_nome"))
            tipo_ativo = str(t.get("tipo_ativo") or "").upper()
            platform_pnl = t.get("pnl_realizado")

            if preco_ent <= 0:
                continue

            # 1. Determina a quantidade simulada
            is_futuro = "FUT" in ticker or "FUTUROS" in tipo_ativo
            if is_futuro:
                sim_qty = 1.0
            elif sizing_mode == "exact_copy":
                sim_qty = orig_qtd
            elif sizing_mode == "fixed_quantity":
                sim_qty = float(fixed_quantity)
            else:  # fixed_capital
                # Opções na B3: múltiplos de 100
                calculated = math.floor(fixed_capital / preco_ent / 100.0) * 100.0
                sim_qty = max(calculated, 100.0)

            # 2. Calcula PnL do trade
            if sizing_mode == "exact_copy" and platform_pnl is not None:
                trade_pnl = float(platform_pnl)
            else:
                if is_futuro:
                    # Em futuros (WIN/WDO), usa a proporção do PnL da plataforma se existir
                    pts = float(t.get("pnl_pontos") or 0)
                    if "WIN" in ticker:
                        trade_pnl = pts * 0.20 * sim_qty  # WIN: R$ 0,20 por ponto
                    elif "WDO" in ticker:
                        trade_pnl = pts * 10.0 * sim_qty   # WDO: R$ 10,00 por ponto
                    elif platform_pnl is not None:
                        trade_pnl = float(platform_pnl) * (sim_qty / max(orig_qtd, 1.0))
                    else:
                        diff = (preco_sai - preco_ent) if lado in ["BUY", "COMPRA"] else (preco_ent - preco_sai)
                        trade_pnl = diff * sim_qty
                else:
                    diff = (preco_sai - preco_ent) if lado in ["BUY", "COMPRA"] else (preco_ent - preco_sai)
                    trade_pnl = diff * sim_qty

            total_trades += 1
            if trade_pnl > 0:
                winning_trades += 1
                gross_profit += trade_pnl
            else:
                losing_trades += 1
                gross_loss += abs(trade_pnl)

            current_equity += trade_pnl
            if current_equity > peak_equity:
                peak_equity = current_equity

            drawdown_val = peak_equity - current_equity
            drawdown_pct = (drawdown_val / peak_equity) * 100.0 if peak_equity > 0 else 0.0

            if drawdown_val > max_drawdown_val:
                max_drawdown_val = drawdown_val
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct

            date_str = str(t.get("timestamp_entrada", ""))[:10]
            equity_curve.append({
                "date": date_str,
                "ticker": ticker,
                "trader": trader_nome,
                "pnl": round(trade_pnl, 2),
                "equity": round(current_equity, 2),
                "drawdown": round(drawdown_val, 2)
            })

            # Estatísticas por Trader
            if trader_nome not in trader_stats:
                trader_stats[trader_nome] = {
                    "trader": trader_nome,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "pnl": 0.0
                }
            trader_stats[trader_nome]["trades"] += 1
            if trade_pnl > 0:
                trader_stats[trader_nome]["wins"] += 1
            else:
                trader_stats[trader_nome]["losses"] += 1
            trader_stats[trader_nome]["pnl"] += trade_pnl

            # Estatísticas por Mês
            month_key = date_str[:7] if len(date_str) >= 7 else "Outros"
            monthly_stats[month_key] = monthly_stats.get(month_key, 0.0) + trade_pnl

            simulated_trades.append({
                "id": t.get("id"),
                "ticker": ticker,
                "trader": trader_nome,
                "produto": t.get("produto"),
                "lado": lado,
                "quantidade": int(sim_qty),
                "preco_entrada": round(preco_ent, 2),
                "preco_saida": round(preco_sai, 2),
                "pnl": round(trade_pnl, 2),
                "pnl_pct": round(((preco_sai - preco_ent) / preco_ent) * 100, 2) if preco_ent > 0 else 0,
                "data_entrada": str(t.get("timestamp_entrada", ""))[:19].replace("T", " "),
                "data_saida": str(t.get("timestamp_saida", ""))[:19].replace("T", " ")
            })

        net_profit = current_equity - initial_equity
        win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        roi_pct = (net_profit / initial_equity) * 100.0 if initial_equity > 0 else 0.0
        avg_win = (gross_profit / winning_trades) if winning_trades > 0 else 0.0
        avg_loss = (gross_loss / losing_trades) if losing_trades > 0 else 0.0
        payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        # Formata trader_stats
        traders_ranking = []
        for tr_name, stats in trader_stats.items():
            wr = (stats["wins"] / stats["trades"]) * 100.0 if stats["trades"] > 0 else 0.0
            traders_ranking.append({
                "trader": tr_name,
                "trades": stats["trades"],
                "wins": stats["wins"],
                "win_rate": round(wr, 1),
                "pnl": round(stats["pnl"], 2)
            })
        traders_ranking.sort(key=lambda x: x["pnl"], reverse=True)

        return {
            "summary": {
                "initial_equity": round(initial_equity, 2),
                "final_equity": round(current_equity, 2),
                "net_profit": round(net_profit, 2),
                "roi_pct": round(roi_pct, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2),
                "max_drawdown_val": round(max_drawdown_val, 2),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "payoff": round(payoff, 2)
            },
            "equity_curve": equity_curve,
            "traders_ranking": traders_ranking,
            "monthly_stats": [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly_stats.items())],
            "trades": simulated_trades
        }
