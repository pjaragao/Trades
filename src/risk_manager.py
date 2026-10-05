import math
from datetime import datetime, time as dtime
from typing import Dict, Any, Tuple, Optional, List
from src.utils import normalize_trader_name

class RiskManager:
    """
    Controlador de risco, filtros e dimensionamento de posição.
    """

    def __init__(self, config: dict, logger=None):
        self.risk_cfg = config.get("risk", {})
        self.tf_cfg = config.get("trading_floors", {})
        self.logger = logger

        self.sizing_mode = self.risk_cfg.get("sizing_mode", "fixed_capital")
        self.fixed_capital = float(self.risk_cfg.get("fixed_capital_per_trade", 1000.0))
        self.fixed_quantity = int(self.risk_cfg.get("fixed_quantity", 100))
        self.options_lot_step = int(self.risk_cfg.get("options_lot_step", 100))
        self.max_open_positions = int(self.risk_cfg.get("max_open_positions", 10))
        self.max_slippage_pct = float(self.risk_cfg.get("max_slippage_pct", 5.0))
        self.enforce_market_hours = bool(self.risk_cfg.get("enforce_market_hours", False))

        self.allowed_products: List[str] = self.tf_cfg.get("allowed_products", [])
        self.allowed_traders: List[str] = self.tf_cfg.get("allowed_traders", [])

    def is_market_open(self) -> bool:
        """Verifica se o mercado da B3 está em horário de negociação (10:00 às 17:50, Seg-Sex)."""
        now = datetime.now()
        # 0 = Segunda, 4 = Sexta, 5 = Sábado, 6 = Domingo
        if now.weekday() >= 5:
            return False
        
        market_start = dtime(10, 0, 0)
        market_end = dtime(17, 50, 0)
        current_time = now.time()
        return market_start <= current_time <= market_end

    def validate_trade(self, trade: Dict[str, Any], current_open_count: int) -> Tuple[bool, str]:
        """
        Verifica se o sinal de trade cumpre todas as regras de segurança e filtros.
        Retorna (True, "") ou (False, motivo_da_rejeicao).
        """
        ticker = trade.get("ticker", "")
        trader = trade.get("trader_nome", "")
        produto = trade.get("produto", "")
        tipo_ativo = trade.get("tipo_ativo", "")

        # 1. Filtro de produtos
        if self.allowed_products:
            match_prod = (
                produto in self.allowed_products or 
                ("Opções" in self.allowed_products and tipo_ativo == "OPCOES") or
                ("Desafio Eleições" in self.allowed_products and produto == "Desafio Eleições")
            )
            if not match_prod:
                return False, f"Produto '{produto}' não está na lista de produtos permitidos: {self.allowed_products}"

        # 2. Filtro de traders
        if self.allowed_traders:
            norm_allowed = {normalize_trader_name(t) for t in self.allowed_traders}
            if normalize_trader_name(trader) not in norm_allowed:
                return False, f"Trader '{trader}' não está na lista de traders permitidos: {self.allowed_traders}"

        # 3. Limite de posições simultâneas
        if current_open_count >= self.max_open_positions:
            return False, f"Limite máximo de posições atingido ({current_open_count}/{self.max_open_positions})"

        # 4. Horário do pregão
        if self.enforce_market_hours and not self.is_market_open():
            return False, "Mercado fechado no momento (fora do pregão B3: 10:00 às 17:50)"

        # 5. Preço de entrada válido
        preco_entrada = float(trade.get("preco_entrada") or 0)
        if preco_entrada <= 0:
            return False, f"Preço de entrada inválido ou zerado ({preco_entrada})"

        return True, ""

    def calculate_quantity(self, trade: Dict[str, Any]) -> float:
        """
        Calcula a quantidade a ser executada no MT5 respeitando o sizing_mode e lotes da B3.
        """
        preco_entrada = float(trade.get("preco_entrada") or 1.0)
        sugestao_qtd = float(trade.get("quantidade") or 100.0)
        tipo_ativo = str(trade.get("tipo_ativo", "")).upper()
        ticker = str(trade.get("ticker", "")).upper()

        # Tratamento especial para contratos futuros (WIN, WDO)
        is_futuro = "FUT" in ticker or "FUTUROS" in tipo_ativo
        if is_futuro:
            # Em minicontratos, opera 1 contrato por padrão no modo conservador
            return 1.0

        if self.sizing_mode == "exact_copy":
            return sugestao_qtd

        if self.sizing_mode == "fixed_quantity":
            return float(self.fixed_quantity)

        # Modo default: fixed_capital
        # Quantidade = Capital / Preço, arredondando para múltiplos do lote padrão da B3 (100)
        raw_quantity = self.fixed_capital / preco_entrada
        step = self.options_lot_step

        if raw_quantity < step:
            # Se o capital não comprar nem 1 lote mínimo, opera 1 lote mínimo
            calculated_qty = float(step)
        else:
            # Arredonda para baixo para o múltiplo mais próximo de step
            calculated_qty = float(math.floor(raw_quantity / step) * step)

        return max(calculated_qty, float(step))

    def check_slippage(self, suggested_price: float, current_market_price: float, lado: str) -> Tuple[bool, float]:
        """
        Verifica se a diferença entre preço sugerido e mercado está dentro do aceitável.
        Retorna (dentro_do_limite, slippage_pct).
        """
        if suggested_price <= 0 or current_market_price <= 0:
            return True, 0.0

        slippage_pct = ((current_market_price - suggested_price) / suggested_price) * 100.0

        # Para compra, não aceitamos pagar muito mais caro que o sugerido
        if lado.upper() in ["BUY", "COMPRA"] and slippage_pct > self.max_slippage_pct:
            return False, slippage_pct

        # Para venda, não aceitamos vender muito mais barato que o sugerido
        if lado.upper() in ["SELL", "VENDA"] and slippage_pct < -self.max_slippage_pct:
            return False, slippage_pct

        return True, slippage_pct
