import os
import sys
import argparse
import yaml
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

from src.logger import setup_logger, print_banner, print_trade_table
from src.client_tf import TradingFloorsClient
from src.risk_manager import RiskManager
from src.order_tracker import OrderTracker
from src.mt5_bridge import MT5Bridge
from src.engine import AutomationEngine

console = Console()

def load_config(config_path: str = "config/settings.yaml") -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Arquivo de configuração '{config_path}' não encontrado.")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def show_status(tracker: OrderTracker):
    """Exibe o status de todas as ordens salvas no banco local."""
    all_trades = tracker.get_all_tracked(limit=50)
    if not all_trades:
        console.print("[dim yellow]Nenhuma ordem registrada no banco local até o momento.[/dim yellow]")
        return

    table = Table(title="Histórico de Ordens Rastreadas Localmente", header_style="bold cyan", border_style="dim")
    table.add_column("Ticker", style="bold yellow")
    table.add_column("Lado")
    table.add_column("Trader", style="green")
    table.add_column("Entrada (R$)", justify="right")
    table.add_column("Qtd Exec", justify="right")
    table.add_column("Ticket MT5", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Preço Saída", justify="right")
    table.add_column("Data Criação", style="dim")

    for t in all_trades:
        status = t.get("status", "OPEN")
        status_color = "[green]OPEN[/green]" if status == "OPEN" else ("[yellow]CLOSED[/yellow]" if status == "CLOSED" else "[dim]SKIPPED[/dim]")
        
        table.add_row(
            str(t.get("ticker", "N/A")),
            str(t.get("lado", "BUY")),
            str(t.get("trader_nome", "N/A")),
            f"R$ {float(t.get('preco_entrada_executado') or t.get('preco_entrada_sugerido') or 0):.2f}",
            str(int(float(t.get("quantidade_executada") or 0))),
            f"#{t.get('mt5_ticket', 'N/A')}",
            status_color,
            f"R$ {float(t.get('preco_saida') or 0):.2f}" if t.get('preco_saida') else "-",
            str(t.get("created_at", ""))[:19].replace("T", " ")
        )
    console.print(table)

def main():
    parser = argparse.ArgumentParser(description="Robô de Automação TradingFloors -> MetaTrader 5")
    parser.add_argument("--dry-run", action="store_true", help="Força execução em modo Simulação (sem ordens reais)")
    parser.add_argument("--live", action="store_true", help="Força execução em modo Conta Real no MetaTrader 5")
    parser.add_argument("--sync-all", action="store_true", help="Copia ordens já abertas na plataforma imediatamente")
    parser.add_argument("--status", action="store_true", help="Exibe o relatório de posições locais e encerra")
    parser.add_argument("--check-connection", action="store_true", help="Testa conexão com TradingFloors e exibe ordens ativas")
    args = parser.parse_args()

    # Carrega .env
    env_path = os.path.join(os.path.dirname(__file__), "config", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()

    # Carrega configurações YAML
    config = load_config()

    # Sobrescreve flags CLI se fornecidas
    if args.dry_run:
        config["execution"]["dry_run"] = True
    elif args.live:
        config["execution"]["dry_run"] = False

    if args.sync_all:
        config["execution"]["initial_sync_mode"] = "sync_all_open"

    dry_run = config.get("execution", {}).get("dry_run", True)
    logger = setup_logger()

    # Exibe cabeçalho
    print_banner(version=config.get("app", {}).get("version", "1.0.0"), dry_run=dry_run)

    # Credenciais TradingFloors
    tf_email = os.getenv("TF_EMAIL", "").strip()
    tf_password = os.getenv("TF_PASSWORD", "").strip()
    tf_url = config.get("trading_floors", {}).get("supabase_url", "")
    tf_anon_key = config.get("trading_floors", {}).get("supabase_anon_key", "")

    if not tf_email or not tf_password:
        console.print("[bold red]Erro: TF_EMAIL ou TF_PASSWORD não configurados no config/.env.[/bold red]")
        sys.exit(1)

    # Instancia componentes
    tracker = OrderTracker(db_path="database/trades_tracker.db")
    risk_manager = RiskManager(config=config, logger=logger)
    tf_client = TradingFloorsClient(
        supabase_url=tf_url,
        supabase_anon_key=tf_anon_key,
        email=tf_email,
        password=tf_password,
        logger=logger
    )
    mt5_bridge = MT5Bridge(config=config, dry_run=dry_run, logger=logger)

    # Ação: Apenas checar status local
    if args.status:
        show_status(tracker)
        return

    # Ação: Testar conexão
    if args.check_connection:
        console.print("[cyan]Testando autenticação no TradingFloors...[/cyan]")
        if tf_client.login():
            console.print("[bold green]Conexão TradingFloors: OK![/bold green]")
            open_trades = tf_client.fetch_open_trades()
            print_trade_table(open_trades, title=f"Ordens Abertas na Plataforma ({len(open_trades)} encontradas)")
        else:
            console.print("[bold red]Falha na autenticação do TradingFloors.[/bold red]")
        return

    # Exibe configurações ativas
    console.print(f"[dim]• Modo de Execução: [bold]{'SIMULAÇÃO (DRY-RUN)' if dry_run else 'CONTA REAL'}[/bold][/dim]")
    console.print(f"[dim]• Gestão de Risco: [bold]{risk_manager.sizing_mode}[/bold] (Max R$ {risk_manager.fixed_capital:,.2f} / trade)[/dim]")
    console.print(f"[dim]• Produtos Permitidos: [bold]{config.get('trading_floors', {}).get('allowed_products')}[/bold][/dim]")
    console.print(f"[dim]• Modo Inicial: [bold]{config.get('execution', {}).get('initial_sync_mode')}[/bold][/dim]\n")

    # Inicia o motor
    engine = AutomationEngine(
        config=config,
        tf_client=tf_client,
        risk_manager=risk_manager,
        tracker=tracker,
        mt5_bridge=mt5_bridge,
        logger=logger
    )

    if engine.initialize():
        engine.run()

if __name__ == "__main__":
    main()
