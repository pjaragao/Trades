import os
import time
from typing import Dict, Any, Optional, Tuple

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

class MT5Bridge:
    """
    Ponte de integração e envio de ordens ao terminal MetaTrader 5.
    Possui suporte transparente ao modo Simulação (Dry-Run).
    """

    def __init__(self, config: dict, dry_run: bool = True, logger=None):
        self.config = config
        self.mt5_cfg = config.get("mt5", {})
        self.dry_run = dry_run
        self.logger = logger

        self.terminal_path = self.mt5_cfg.get("terminal_path", "").strip()
        self.magic_number = int(self.mt5_cfg.get("magic_number", 998877))
        self.deviation_points = int(self.mt5_cfg.get("deviation_points", 10))
        self.order_type_pref = self.mt5_cfg.get("order_type", "limit").lower()

        self.is_connected = False
        self._simulated_ticket_counter = 80000001

    def _log_info(self, msg: str):
        if self.logger:
            self.logger.info(msg)

    def _log_error(self, msg: str):
        if self.logger:
            self.logger.error(msg)

    def connect(self, login: Optional[int] = None, password: Optional[str] = None, server: Optional[str] = None) -> bool:
        """Inicializa a conexão com o terminal MetaTrader 5 local."""
        if self.dry_run:
            self._log_info("[MT5-SIMULAÇÃO] Modo Dry-Run ativo. Conexão MT5 simulada com sucesso.")
            self.is_connected = True
            return True

        if not MT5_AVAILABLE:
            self._log_error("Biblioteca 'MetaTrader5' não está instalada no ambiente Python.")
            return False

        init_args = {}
        if self.terminal_path and os.path.exists(self.terminal_path):
            init_args["path"] = self.terminal_path

        # Tenta inicializar terminal
        init_ok = mt5.initialize(**init_args)
        if not init_ok:
            err = mt5.last_error()
            self._log_error(f"Falha ao inicializar o terminal MT5: {err}")
            self.is_connected = False
            return False

        # Login opcional se fornecido
        if login and password and server:
            logged_in = mt5.login(login=int(login), password=str(password), server=str(server))
            if not logged_in:
                self._log_error(f"Falha no login da conta MT5 {login} no servidor {server}: {mt5.last_error()}")
                return False

        acc = mt5.account_info()
        if acc:
            self._log_info(f"Conectado ao MT5! Conta: {acc.login} | Corretora: {acc.company} | Saldo: R$ {acc.balance:,.2f}")
            self.is_connected = True
            return True
        else:
            self._log_error("Não foi possível obter dados da conta do MT5.")
            return False

    def disconnect(self):
        """Encerra a conexão com o MT5."""
        if MT5_AVAILABLE and not self.dry_run:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self.is_connected = False

    def get_symbol_market_price(self, symbol: str) -> Optional[Tuple[float, float]]:
        """Retorna tupla (bid, ask) atual para o ativo selecionado."""
        if self.dry_run or not self.is_connected:
            return None

        # Garante que o símbolo está visível no Market Watch
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick and tick.bid > 0 and tick.ask > 0:
            return tick.bid, tick.ask
        return None

    def execute_entry(
        self,
        symbol: str,
        lado: str,
        quantidade: float,
        preco_sugerido: float,
        comment: str = "TF Bot Entry"
    ) -> Dict[str, Any]:
        """
        Executa a ordem de entrada (compra ou venda) de acordo com o sinal recebido.
        """
        if self.dry_run:
            ticket = self._simulated_ticket_counter
            self._simulated_ticket_counter += 1
            return {
                "success": True,
                "ticket": ticket,
                "price": preco_sugerido,
                "volume": quantidade,
                "symbol": symbol,
                "comment": f"[DRY-RUN] {comment}",
                "simulated": True
            }

        if not self.is_connected:
            return {"success": False, "error": "MT5 não está conectado."}

        # 1. Habilita o símbolo dinamicamente no MT5
        if not mt5.symbol_select(symbol, True):
            return {"success": False, "error": f"Símbolo '{symbol}' não encontrado ou não permitido no MT5."}

        # 2. Obtém cotação do ativo
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"success": False, "error": f"Não foi possível obter cotações para '{symbol}'."}

        is_buy = lado.upper() in ["BUY", "COMPRA"]
        order_price = preco_sugerido

        # 3. Monta a requisição MT5
        if self.order_type_pref == "market":
            trade_action = mt5.TRADE_ACTION_DEAL
            order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            order_price = tick.ask if is_buy else tick.bid
        else:
            trade_action = mt5.TRADE_ACTION_PENDING
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT

        request = {
            "action": trade_action,
            "symbol": symbol,
            "volume": float(quantidade),
            "type": order_type,
            "price": float(order_price),
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": comment[:31], # MT5 limita tamanho de comentário
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        # 4. Dispara a ordem
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            ticket = result.order or result.deal
            self._log_info(f"Ordem MT5 enviada com sucesso! Ticket: {ticket} ({symbol})")
            return {
                "success": True,
                "ticket": ticket,
                "price": result.price or order_price,
                "volume": quantidade,
                "symbol": symbol,
                "retcode": result.retcode,
                "simulated": False
            }
        else:
            retcode = result.retcode if result else "N/A"
            comment_err = result.comment if result else mt5.last_error()
            self._log_error(f"Erro ao enviar ordem MT5 para {symbol}: Retcode {retcode} - {comment_err}")
            return {
                "success": False,
                "retcode": retcode,
                "error": str(comment_err)
            }

    def execute_exit(
        self,
        symbol: str,
        lado_original: str,
        quantidade: float,
        ticket: Optional[int] = None,
        preco_saida_sugerido: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Fecha uma posição existente no MT5.
        """
        if self.dry_run:
            return {
                "success": True,
                "ticket": ticket or self._simulated_ticket_counter,
                "price": preco_saida_sugerido or 0.0,
                "symbol": symbol,
                "simulated": True
            }

        if not self.is_connected:
            return {"success": False, "error": "MT5 não está conectado."}

        # Para fechar posição comprada, envia VENDA a mercado; para posição vendida, envia COMPRA.
        is_buy_exit = lado_original.upper() not in ["BUY", "COMPRA"]
        order_type = mt5.ORDER_TYPE_BUY if is_buy_exit else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(symbol)
        exit_price = (tick.ask if is_buy_exit else tick.bid) if tick else (preco_saida_sugerido or 0.0)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(quantidade),
            "type": order_type,
            "price": float(exit_price),
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": "TF Bot Exit",
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        # Se houver position_id associado, inclui na requisição de fechamento
        if ticket:
            request["position"] = ticket

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._log_info(f"Saída MT5 concluída com sucesso! ({symbol})")
            return {
                "success": True,
                "ticket": result.order or result.deal,
                "price": result.price or exit_price,
                "simulated": False
            }
        else:
            err = result.comment if result else mt5.last_error()
            self._log_error(f"Erro ao fechar posição MT5 de {symbol}: {err}")
            return {"success": False, "error": str(err)}
