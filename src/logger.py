import os
import sys
import logging
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console(force_terminal=True)

def setup_logger(log_dir: str = "logs") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"bot_{today_str}.log")

    logger = logging.getLogger("TradingFloorsBot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # File Handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

def print_banner(version: str = "1.0.0", dry_run: bool = True):
    mode_text = "[bold yellow]SIMULAÇÃO (DRY-RUN)[/bold yellow]" if dry_run else "[bold red]REAL (LIVE TRADING)[/bold red]"
    banner_text = Text()
    banner_text.append("TRADING FLOORS -> METATRADER 5 BOT\n", style="bold cyan")
    banner_text.append(f"Versão: {version} | Modo: ", style="dim")
    banner_text.append(f"{'SIMULAÇÃO (DRY-RUN)' if dry_run else 'CONTA REAL'}\n", style="bold yellow" if dry_run else "bold red")
    banner_text.append("Sincronização automatizada de sinais B3 (Ações, Opções e Futuros)\n", style="italic white")
    
    console.print(Panel(banner_text, border_style="cyan", expand=False))

def print_trade_table(trades: list, title: str = "Ordens em Aberto no TradingFloors"):
    if not trades:
        console.print(f"[dim yellow]Nenhuma ordem para exibir ({title}).[/dim yellow]")
        return

    table = Table(title=title, header_style="bold magenta", border_style="dim")
    table.add_column("Produto", style="cyan")
    table.add_column("Trader", style="green")
    table.add_column("Ticker", style="bold yellow")
    table.add_column("Lado", style="white")
    table.add_column("Entrada (R$)", justify="right")
    table.add_column("Preço Atual", justify="right")
    table.add_column("Qtd Sugerida", justify="right")
    table.add_column("Data/Hora", style="dim")
    table.add_column("Status", style="bold")

    for t in trades:
        lado = str(t.get("lado", "BUY")).upper()
        lado_style = "[bold green]COMPRA[/bold green]" if lado in ["BUY", "COMPRA"] else "[bold red]VENDA[/bold red]"
        
        status = str(t.get("status", "OPEN")).upper()
        status_style = "[bold green]ABERTO[/bold green]" if status == "OPEN" else "[dim red]FECHADO[/dim red]"

        preco_ent = f"R$ {float(t.get('preco_entrada', 0) or 0):.2f}"
        preco_atu = f"R$ {float(t.get('preco_atual', 0) or 0):.2f}" if t.get('preco_atual') is not None else "-"
        qtd = f"{int(float(t.get('quantidade', 0) or 0)):,}".replace(",", ".")

        data_raw = str(t.get("timestamp_entrada", "") or "")[:19].replace("T", " ")

        table.add_row(
            str(t.get("produto", "N/A")),
            str(t.get("trader_nome", "N/A")),
            str(t.get("ticker", "N/A")),
            lado_style,
            preco_ent,
            preco_atu,
            qtd,
            data_raw,
            status_style
        )

    console.print(table)

def log_trade_event(event_type: str, trade: dict, mt5_res: dict = None, dry_run: bool = True):
    ticker = trade.get("ticker", "UNKNOWN")
    trader = trade.get("trader_nome", "N/A")
    lado = trade.get("lado", "BUY")
    preco = trade.get("preco_entrada", 0)
    qtd = trade.get("exec_quantity", trade.get("quantidade", 0))
    tag = "[bold yellow][DRY-RUN][/bold yellow]" if dry_run else "[bold green][LIVE][/bold green]"

    if event_type == "ENTRY":
        console.print(
            f"{tag} [bold green]NOVA ENTRADA EXECUTADA:[/bold green] "
            f"[bold yellow]{ticker}[/bold yellow] ({lado}) | Trader: {trader} | "
            f"Qtd: [bold]{int(qtd)}[/bold] | Preço: [bold]R$ {preco:.2f}[/bold] | "
            f"Ticket MT5: #{mt5_res.get('ticket', 'SIMULADO') if mt5_res else 'N/A'}"
        )
    elif event_type == "EXIT":
        preco_saida = trade.get("preco_saida", 0)
        console.print(
            f"{tag} [bold magenta]POSIÇÃO ENCERRADA:[/bold magenta] "
            f"[bold yellow]{ticker}[/bold yellow] | Trader: {trader} | "
            f"Preço Saída: [bold]R$ {preco_saida:.2f}[/bold] | "
            f"Ticket MT5: #{mt5_res.get('ticket', 'SIMULADO') if mt5_res else 'N/A'}"
        )
    elif event_type == "REJECTED":
        reason = trade.get("reject_reason", "Não atende aos critérios de risco")
        console.print(
            f"[yellow]SINAL IGNORADO:[/yellow] {ticker} | Trader: {trader} | Motivo: [red]{reason}[/red]"
        )
