import json
import os
from typing import List, Dict, Any
from strategies.screeners.put_selling_screener import PutSellingScreener

class StrategyTradeMatcher:
    """Mapeia operações ativas e sinais de mercado diretamente para seus setups e estratégias correspondentes."""

    def __init__(self):
        self.catalog_path = "strategies/knowledge_base/catalog.json"
        self.strategies_index = self._load_catalog_index()

    def _load_catalog_index(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.catalog_path):
            return {}
        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {s["id"]: s for s in data.get("strategies", [])}
        except Exception:
            return {}

    def map_trades_to_strategies(self, open_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Recebe a lista de trades abertos (já deduplicados) e as oportunidades do screener
        e retorna agrupamento detalhado por estratégia.
        """
        mapped_trades = []
        strategy_stats = {}

        # 1. Mapeia trades abertos do TradingFloor
        for t in open_trades:
            trader = (t.get("trader_nome") or "").strip().title()
            ticker = (t.get("ticker") or "").strip().upper()
            tipo_ativo = t.get("tipo_ativo") or "OPCOES"
            preco_ent = float(t.get("preco_entrada") or 0)
            preco_atu = float(t.get("preco_atual")) if t.get("preco_atual") is not None else None
            pnl_pct = None
            if preco_atu is not None and preco_ent > 0:
                lado = (t.get("lado") or "BUY").upper()
                pnl_pct = round(((preco_atu - preco_ent) / preco_ent * 100) if lado == "BUY" else ((preco_ent - preco_atu) / preco_ent * 100), 2)

            # Classificação por Trader / Estratégia
            strat_id = None
            setup_rule = ""
            alvo_sugerido = None
            stop_sugerido = None

            if "Ferri" in trader:
                strat_id = "STRAT-TF-004"
                setup_rule = "Compra a seco assimétrica em opções com alvo multiplicador (2x a 3x)"
                alvo_sugerido = round(preco_ent * 2.5, 2)
                stop_sugerido = round(preco_ent * 0.5, 2)
            elif "Sanita" in trader:
                strat_id = "STRAT-TF-003"
                setup_rule = "Rompimento de consolidação com momentum direcional"
                alvo_sugerido = round(preco_ent * 2.0, 2)
                stop_sugerido = round(preco_ent * 0.6, 2)
            elif "Artur Horta" in trader:
                strat_id = "STRAT-TF-005"
                setup_rule = "Divergência de IFR e assimetria em small caps / opções"
                alvo_sugerido = round(preco_ent * 2.2, 2)
                stop_sugerido = round(preco_ent * 0.55, 2)
            elif "Guilherme" in trader or ticker == "WDOFUT":
                strat_id = "STRAT-TF-006"
                setup_rule = "Scalping de fluxo cambial intraday no mini-dólar futuro"
                alvo_sugerido = round(preco_ent + 8.0, 1)
                stop_sugerido = round(preco_ent - 4.5, 1)
            elif "Calvete" in trader:
                strat_id = "STRAT-TF-002"
                setup_rule = "Níveis de suporte/resistência e pullback com parciais rápidas"
                alvo_sugerido = round(preco_ent + 300, 0)
                stop_sugerido = round(preco_ent - 180, 0)
            elif "Amilton" in trader:
                strat_id = "STRAT-TF-007"
                setup_rule = "Swing trade alinhado à média móvel de 20 períodos"
                alvo_sugerido = round(preco_ent * 1.05, 2)
                stop_sugerido = round(preco_ent * 0.97, 2)
            elif "Corleta" in trader:
                strat_id = "STRAT-TF-009"
                setup_rule = "Operação direcional a favor da tendência em futuros e blue chips"
                alvo_sugerido = round(preco_ent * 1.04, 2)
                stop_sugerido = round(preco_ent * 0.98, 2)
            else:
                # Default para WINFUT
                if "WIN" in ticker:
                    strat_id = "STRAT-TF-001"
                    setup_rule = "Scalping ágil no book de ofertas de mini-índice"
                    alvo_sugerido = round(preco_ent + 150, 0)
                    stop_sugerido = round(preco_ent - 120, 0)
                else:
                    strat_id = "STRAT-TF-003"
                    setup_rule = "Operação tática direcional do TradingFloor"
                    alvo_sugerido = round(preco_ent * 1.5, 2)
                    stop_sugerido = round(preco_ent * 0.7, 2)

            strat_meta = self.strategies_index.get(strat_id, {})
            strat_name = strat_meta.get("name", "Estratégia TradingFloor")
            win_rate = strat_meta.get("win_rate_pct", 60.0)

            # Aderência ao setup
            adherence = "Dentro dos parâmetros normais"
            if pnl_pct is not None:
                if pnl_pct >= 50.0:
                    adherence = "🎯 Alvo parcial atingido (+50%)"
                elif pnl_pct <= -40.0:
                    adherence = "⚠️ Próximo da região de stop"

            mapped_trades.append({
                "trade_id": t.get("id"),
                "strategy_id": strat_id,
                "strategy_name": strat_name,
                "source": f"TradingFloor ({trader})",
                "win_rate_pct": win_rate,
                "ticker": ticker,
                "tipo_ativo": tipo_ativo,
                "produto": t.get("produto_display") or t.get("produto") or "Trading Floor",
                "lado": t.get("lado") or "BUY",
                "quantidade": t.get("quantidade") or 100,
                "preco_entrada": preco_ent,
                "preco_atual": preco_atu,
                "pnl_pct": pnl_pct,
                "setup_rule": setup_rule,
                "alvo_sugerido": alvo_sugerido,
                "stop_sugerido": stop_sugerido,
                "adherence": adherence,
                "timestamp_entrada": t.get("timestamp_entrada", ""),
                "is_screener_opportunity": False
            })

        # 2. Mapeia Oportunidades do Screener da Estratégia STRAT-YT-001 (Venda de Put OTM -1 ATR)
        try:
            put_screener = PutSellingScreener()
            opps = put_screener.scan_all()
            for opp in opps:
                std = opp.get("standard_setup", {})
                strike = std.get("strike", 0)
                prem = std.get("estimated_premium", 0)
                curr = opp.get("current_price", 0)
                margin = std.get("safety_margin_pct", 0)
                yield_cdi = std.get("total_monthly_yield_with_cdi_pct", 0)
                multiple = std.get("cdi_multiple", 0)

                mapped_trades.append({
                    "trade_id": f"SCREENER-PUT-{opp['symbol']}",
                    "strategy_id": "STRAT-YT-001",
                    "strategy_name": "Venda de Put OTM no Nível -1 ATR (Renda 300% CDI)",
                    "source": "YouTube (Jimmy Carvalho Screener)",
                    "win_rate_pct": 99.0,
                    "ticker": f"{opp['symbol']} (Put Strike R$ {strike:.2f})",
                    "tipo_ativo": "OPCOES (Sinal Screener)",
                    "produto": "Screener B3",
                    "lado": "SELL",
                    "quantidade": 1000,
                    "preco_entrada": prem,
                    "preco_atual": prem,
                    "pnl_pct": 0.0,
                    "setup_rule": f"Venda de Put no strike R$ {strike:.2f} (-{margin}% de queda) com cobertura no CDI",
                    "alvo_sugerido": 0.01,
                    "stop_sugerido": round(prem * 3.0, 2),
                    "adherence": f"Margem de -{margin}% (1 ATR) | Retorno: {yield_cdi}% ({multiple}x CDI)",
                    "timestamp_entrada": opp.get("expiration_date", ""),
                    "is_screener_opportunity": True
                })
        except Exception as e:
            print(f"Erro ao incluir sinais do screener em strategy_trades: {e}")

        # Estatísticas por estratégia
        for mt in mapped_trades:
            sid = mt["strategy_id"]
            if sid not in strategy_stats:
                strategy_stats[sid] = {
                    "strategy_id": sid,
                    "strategy_name": mt["strategy_name"],
                    "source": mt["source"],
                    "win_rate_pct": mt["win_rate_pct"],
                    "count": 0
                }
            strategy_stats[sid]["count"] += 1

        return {
            "total_trades": len(mapped_trades),
            "trades": mapped_trades,
            "strategies_summary": list(strategy_stats.values())
        }
