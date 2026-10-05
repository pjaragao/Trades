import os
import sys
import yaml
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from src.execution.legacy.logger import setup_logger, print_banner, print_trade_table
from src.execution.legacy.client_tf import TradingFloorsClient
from src.execution.legacy.risk_manager import RiskManager
from src.execution.legacy.order_tracker import OrderTracker
from src.execution.mt5_bridge import MT5Bridge

console = Console(force_terminal=True)

def run_test():
    load_dotenv("config/.env")
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Força Dry-Run
    config["execution"]["dry_run"] = True
    logger = setup_logger()

    print_banner(version="1.0.0", dry_run=True)
    console.print("[bold cyan]Iniciando Teste de Validação em Modo Simulado...[/bold cyan]\n")

    tf_email = os.getenv("TF_EMAIL", "").strip()
    tf_password = os.getenv("TF_PASSWORD", "").strip()
    tf_url = config["trading_floors"]["supabase_url"]
    tf_anon_key = config["trading_floors"]["supabase_anon_key"]

    tf_client = TradingFloorsClient(tf_url, tf_anon_key, tf_email, tf_password, logger=logger)
    tracker = OrderTracker(db_path="database/test_tracker.db")
    risk_manager = RiskManager(config=config, logger=logger)
    mt5_bridge = MT5Bridge(config=config, dry_run=True, logger=logger)

    # 1. Login
    console.print("[1/4] Testando autenticação...")
    if not tf_client.login():
        console.print("[red]Falha no login![/red]")
        return
    console.print("[green][OK] Login efetuado com sucesso no TradingFloors![/green]\n")

    # 2. Busca operações abertas
    console.print("[2/4] Consultando operações ativas...")
    allowed_prods = config["trading_floors"]["allowed_products"]
    open_trades = tf_client.fetch_open_trades(allowed_prods)
    console.print(f"[green][OK] Encontradas {len(open_trades)} operações ativas nos produtos {allowed_prods}[/green]\n")
    print_trade_table(open_trades, title="Operações Ativas Encontradas")

    # 3. Simulação de dimensionamento e risco
    console.print("\n[3/4] Simulando dimensionamento de risco para cada operação:")
    for t in open_trades[:5]:
        ticker = t.get("ticker")
        preco_entrada = float(t.get("preco_entrada") or 0)
        sug_qtd = float(t.get("quantidade") or 0)
        is_valid, reason = risk_manager.validate_trade(t, current_open_count=0)
        
        if is_valid:
            calc_qty = risk_manager.calculate_quantity(t)
            custo_total = calc_qty * preco_entrada
            console.print(
                f"  • [bold yellow]{ticker}[/bold yellow] ({t.get('lado')}) | Preço: R$ {preco_entrada:.2f} | "
                f"Sugerido: {int(sug_qtd)} un | [bold green]Dimensionado: {int(calc_qty)} un[/bold green] "
                f"(Total: R$ {custo_total:,.2f})"
            )
        else:
            console.print(f"  • [yellow]{ticker}[/yellow] -> [red]Rejeitado pelo risco: {reason}[/red]")

    # 4. Simulação de Envio MT5
    console.print("\n[4/4] Simulando envio de ordem para a primeira recomendação:")
    if open_trades:
        first = open_trades[0]
        qty = risk_manager.calculate_quantity(first)
        res = mt5_bridge.execute_entry(
            symbol=first["ticker"],
            lado=first.get("lado", "BUY"),
            quantidade=qty,
            preco_sugerido=float(first.get("preco_entrada") or 0),
            comment="TF Bot Test"
        )
        console.print(f"  • Retorno MT5 Simulado: {res}")
        console.print("\n[bold green][OK] Todos os testes de fluxo foram concluídos com sucesso![/bold green]")

if __name__ == "__main__":
    run_test()
