import time
import signal
import sys
from typing import Dict, Any, List
from rich.console import Console

from src.client_tf import TradingFloorsClient
from src.risk_manager import RiskManager
from src.order_tracker import OrderTracker
from src.mt5_bridge import MT5Bridge
from src.logger import log_trade_event, print_trade_table, print_banner

console = Console()

class AutomationEngine:
    """
    Motor central de orquestração do robô.
    Conecta a detecção de sinais da TradingFloors à execução de ordens no MetaTrader 5.
    """

    def __init__(
        self,
        config: dict,
        tf_client: TradingFloorsClient,
        risk_manager: RiskManager,
        tracker: OrderTracker,
        mt5_bridge: MT5Bridge,
        logger=None
    ):
        self.config = config
        self.tf_client = tf_client
        self.risk_manager = risk_manager
        self.tracker = tracker
        self.mt5_bridge = mt5_bridge
        self.logger = logger

        self.poll_interval = int(config.get("execution", {}).get("poll_interval_seconds", 5))
        self.initial_sync_mode = config.get("execution", {}).get("initial_sync_mode", "only_new")
        self.dry_run = bool(config.get("execution", {}).get("dry_run", True))
        self.allowed_products = config.get("trading_floors", {}).get("allowed_products", [])

        self.running = False
        self._setup_signals()

    def _setup_signals(self):
        # signal.signal só pode ser chamado na thread principal (no Flask o motor roda em outra thread)
        import threading
        if threading.current_thread() is not threading.main_thread():
            return

        def handle_exit(sig, frame):
            console.print("\n[bold yellow]Sinal de encerramento recebido. Desconectando com segurança...[/bold yellow]")
            self.stop()

        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)

    def initialize(self) -> bool:
        """Efetua autenticação inicial e prepara os serviços."""
        console.print("[cyan]Autenticando na plataforma TradingFloors...[/cyan]")
        if not self.tf_client.login():
            console.print("[bold red]Falha na autenticação do TradingFloors. Verifique seu e-mail e senha no config/.env.[/bold red]")
            return False

        console.print("[green]Autenticação no TradingFloors bem-sucedida![/green]")

        console.print(f"[cyan]Conectando ao MetaTrader 5 (Modo: {'Simulação' if self.dry_run else 'Real'})...[/cyan]")
        if not self.mt5_bridge.connect():
            if not self.dry_run:
                console.print("[bold red]Não foi possível conectar ao terminal MetaTrader 5.[/bold red]")
                return False

        # Sincronização inicial
        open_trades = self.tf_client.fetch_open_trades(self.allowed_products)
        console.print(f"[cyan]Total de operações abertas na plataforma no momento: [bold]{len(open_trades)}[/bold][/cyan]")

        if self.initial_sync_mode == "only_new":
            console.print("[dim yellow]Modo 'only_new' ativo: marcando posições antigas existentes como já observadas.[/dim yellow]")
            for t in open_trades:
                trade_id = t["id"]
                if not self.tracker.is_trade_processed(trade_id):
                    self.tracker.mark_skipped(
                        trade_id=trade_id,
                        ticker=t.get("ticker", ""),
                        trader_nome=t.get("trader_nome", ""),
                        produto=t.get("produto", ""),
                        reason="Ignorado no startup (modo only_new)"
                    )
            console.print("[bold green]Monitoramento ativo! Aguardando novos sinais em tempo real...[/bold green]")
        else:
            console.print("[bold yellow]Modo 'sync_all_open' ativo: sincronizando ordens abertas existentes...[/bold yellow]")
            self._process_entries(open_trades)

        return True

    def _process_entries(self, open_trades: List[Dict[str, Any]]):
        """Verifica se há novos trades abertos que ainda não foram processados."""
        current_tracked_open = self.tracker.get_open_synced_trades()
        open_count = len(current_tracked_open)

        for trade in open_trades:
            trade_id = trade["id"]

            # Se já foi processado anteriormente, pula
            if self.tracker.is_trade_processed(trade_id):
                continue

            ticker = trade.get("ticker", "UNKNOWN")
            trader = trade.get("trader_nome", "N/A")
            lado = trade.get("lado", "BUY")
            preco_sug = float(trade.get("preco_entrada") or 0)
            qtd_sug = float(trade.get("quantidade") or 100)
            produto = trade.get("produto", "N/A")
            source_table = trade.get("_source_table", "trades")

            # Validação de Risco
            is_valid, reject_reason = self.risk_manager.validate_trade(trade, open_count)
            if not is_valid:
                trade["reject_reason"] = reject_reason
                log_trade_event("REJECTED", trade, dry_run=self.dry_run)
                self.tracker.mark_skipped(trade_id, ticker, trader, produto, reject_reason)
                continue

            # Dimensionamento de lote
            exec_qty = self.risk_manager.calculate_quantity(trade)
            trade["exec_quantity"] = exec_qty

            # Envio para o MetaTrader 5
            exec_res = self.mt5_bridge.execute_entry(
                symbol=ticker,
                lado=lado,
                quantidade=exec_qty,
                preco_sugerido=preco_sug,
                comment=f"TF {trader}"
            )

            if exec_res.get("success"):
                mt5_ticket = exec_res.get("ticket", 0)
                self.tracker.record_entry(
                    trade_id=trade_id,
                    source_table=source_table,
                    produto=produto,
                    ticker=ticker,
                    trader_nome=trader,
                    lado=lado,
                    preco_entrada_sugerido=preco_sug,
                    preco_entrada_executado=exec_res.get("price", preco_sug),
                    quantidade_sugerida=qtd_sug,
                    quantidade_executada=exec_qty,
                    mt5_ticket=mt5_ticket,
                    timestamp_entrada=trade.get("timestamp_entrada", ""),
                    status="OPEN"
                )
                open_count += 1
                log_trade_event("ENTRY", trade, exec_res, dry_run=self.dry_run)
            else:
                err_msg = exec_res.get("error", "Falha de envio MT5")
                console.print(f"[bold red]Falha ao executar ordem no MT5 ({ticker}): {err_msg}[/bold red]")

    def _process_exits(self):
        """Verifica se alguma posição aberta monitorada localmente foi encerrada na plataforma."""
        open_tracked = self.tracker.get_open_synced_trades()
        if not open_tracked:
            return

        for tracked in open_tracked:
            trade_id = tracked["trade_id"]
            source_table = tracked.get("source_table", "trades")

            current_state = self.tf_client.fetch_trade_by_id(trade_id, source_table)
            if not current_state:
                continue

            status = str(current_state.get("status", "OPEN")).upper()
            preco_saida = current_state.get("preco_saida")

            # Se a plataforma marcou como CLOSED ou informou preco_saida, encerra a posição no MT5
            if status == "CLOSED" or (preco_saida is not None and float(preco_saida) > 0):
                preco_saida_val = float(preco_saida or 0)
                ticker = tracked["ticker"]
                ticket = tracked.get("mt5_ticket")
                lado = tracked.get("lado", "BUY")
                qty = float(tracked.get("quantidade_executada") or 100)

                exit_res = self.mt5_bridge.execute_exit(
                    symbol=ticker,
                    lado_original=lado,
                    quantidade=qty,
                    ticket=ticket,
                    preco_saida_sugerido=preco_saida_val
                )

                if exit_res.get("success"):
                    pnl_realizado = current_state.get("pnl_realizado")
                    ts_saida = current_state.get("timestamp_saida")

                    self.tracker.record_exit(
                        trade_id=trade_id,
                        preco_saida=preco_saida_val,
                        timestamp_saida=ts_saida,
                        pnl_realizado=float(pnl_realizado) if pnl_realizado else None
                    )

                    tracked["preco_saida"] = preco_saida_val
                    log_trade_event("EXIT", tracked, exit_res, dry_run=self.dry_run)

    def run(self):
        """Loop principal de monitoramento contínuo."""
        self.running = True
        console.print(f"[dim]Loop de verificação ativo a cada {self.poll_interval} segundos. Pressione Ctrl+C para parar.[/dim]\n")

        iter_count = 0
        while self.running:
            try:
                open_trades = self.tf_client.fetch_open_trades(self.allowed_products)
                self._process_entries(open_trades)
                self._process_exits()

                iter_count += 1
                if iter_count % 12 == 0:  # Exibe batimento de coração a cada 1 minuto
                    active_count = len(self.tracker.get_open_synced_trades())
                    console.print(f"[dim]{time.strftime('%H:%M:%S')} - Monitorando TradingFloors... ({active_count} posições ativas acompanhadas)[/dim]")

                time.sleep(self.poll_interval)
            except Exception as e:
                console.print(f"[bold red]Erro no loop de execução: {e}[/bold red]")
                if self.logger:
                    self.logger.exception("Erro não tratado no loop principal")
                time.sleep(self.poll_interval)

    def stop(self):
        """Para a execução do motor e desconecta recursos."""
        self.running = False
        self.mt5_bridge.disconnect()
        console.print("[bold green]Robô finalizado com sucesso.[/bold green]")
