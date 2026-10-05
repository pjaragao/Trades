import os
import threading
import time
import logging
from typing import Optional, Dict, Any, List
from collections import deque

import yaml
from dotenv import load_dotenv

from src.client_tf import TradingFloorsClient
from src.risk_manager import RiskManager
from src.order_tracker import OrderTracker
from src.mt5_bridge import MT5Bridge
from src.engine import AutomationEngine

class BotService:
    """
    Controlador de ciclo de vida do robô para integração com a interface Web.
    Permite iniciar, pausar, alterar parâmetros e consultar logs em tempo real.
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = BotService()
        return cls._instance

    def __init__(self, config_path: str = "config/settings.yaml", env_path: str = "config/.env"):
        self.config_path = config_path
        self.env_path = env_path
        
        self.engine: Optional[AutomationEngine] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self.start_time: Optional[float] = None
        
        # Buffer circular em memória para os últimos 500 logs da interface web
        self.log_buffer = deque(maxlen=500)
        self._setup_logging()

    def _setup_logging(self):
        class WebLogHandler(logging.Handler):
            def __init__(self, buffer):
                super().__init__()
                self.buffer = buffer

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.buffer.append({
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "level": record.levelname,
                        "message": msg
                    })
                except Exception:
                    pass

        from datetime import datetime
        logger = logging.getLogger("TradingFloorsBot")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(message)s")
        handler = WebLogHandler(self.log_buffer)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        self.logger = logger

    def log(self, message: str, level: str = "INFO"):
        self.log_buffer.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message
        })

    def load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_config(self, new_config: dict) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(new_config, f, allow_unicode=True, default_flow_style=False)
            self.log("Configurações atualizadas e salvas com sucesso.")
            return True
        except Exception as e:
            self.log(f"Erro ao salvar configurações: {e}", "ERROR")
            return False

    def get_status(self) -> Dict[str, Any]:
        config = self.load_config()
        dry_run = config.get("execution", {}).get("dry_run", True)
        tracker = OrderTracker()
        open_tracked = tracker.get_open_synced_trades()

        uptime_seconds = int(time.time() - self.start_time) if self.is_running and self.start_time else 0
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        mt5_connected = False
        if self.engine and self.engine.mt5_bridge:
            mt5_connected = self.engine.mt5_bridge.is_connected

        return {
            "is_running": self.is_running,
            "dry_run": dry_run,
            "uptime": uptime_str,
            "open_positions_count": len(open_tracked),
            "mt5_connected": mt5_connected,
            "poll_interval": config.get("execution", {}).get("poll_interval_seconds", 5),
            "sizing_mode": config.get("risk", {}).get("sizing_mode", "fixed_capital"),
            "fixed_capital": config.get("risk", {}).get("fixed_capital_per_trade", 1000.0),
            "allowed_products": config.get("trading_floors", {}).get("allowed_products", [])
        }

    def start_bot(self, dry_run: Optional[bool] = None) -> Dict[str, Any]:
        if self.is_running:
            return {"success": False, "error": "O robô já está em execução."}

        try:
            load_dotenv(self.env_path)
            config = self.load_config()

            if dry_run is not None:
                config["execution"]["dry_run"] = dry_run
                self.save_config(config)

            is_dry = config.get("execution", {}).get("dry_run", True)

            tf_email = os.getenv("TF_EMAIL", "").strip()
            tf_password = os.getenv("TF_PASSWORD", "").strip()
            tf_url = config.get("trading_floors", {}).get("supabase_url", "")
            tf_anon_key = config.get("trading_floors", {}).get("supabase_anon_key", "")

            tracker = OrderTracker()
            risk_manager = RiskManager(config=config, logger=self.logger)
            tf_client = TradingFloorsClient(tf_url, tf_anon_key, tf_email, tf_password, logger=self.logger)
            mt5_bridge = MT5Bridge(config=config, dry_run=is_dry, logger=self.logger)

            self.engine = AutomationEngine(
                config=config,
                tf_client=tf_client,
                risk_manager=risk_manager,
                tracker=tracker,
                mt5_bridge=mt5_bridge,
                logger=self.logger
            )

            self.log(f"Inicializando robô em modo {'Simulação (Dry-Run)' if is_dry else 'Conta Real'}...")
            if not self.engine.initialize():
                self.log("Falha ao inicializar o motor de automação.", "ERROR")
                return {"success": False, "error": "Falha na inicialização (verifique credenciais ou MT5)."}

            self.is_running = True
            self.start_time = time.time()

            # Executa o loop do robô em thread daemon separada
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

            self.log("Robô iniciado com sucesso! Monitorando sinais em segundo plano.")
            return {"success": True, "message": "Robô iniciado com sucesso."}

        except Exception as e:
            self.is_running = False
            self.log(f"Exceção ao iniciar robô: {e}", "ERROR")
            return {"success": False, "error": str(e)}

    def _run_loop(self):
        try:
            if self.engine:
                self.engine.run()
        except Exception as e:
            self.log(f"Erro no loop do robô: {e}", "ERROR")
        finally:
            self.is_running = False
            self.start_time = None
            self.log("Thread do robô finalizada.")

    def stop_bot(self) -> Dict[str, Any]:
        if not self.is_running:
            return {"success": False, "error": "O robô não está em execução."}

        try:
            self.log("Parando o robô...")
            if self.engine:
                self.engine.stop()
            self.is_running = False
            self.start_time = None
            self.log("Robô pausado com sucesso.")
            return {"success": True, "message": "Robô pausado."}
        except Exception as e:
            self.log(f"Erro ao parar o robô: {e}", "ERROR")
            return {"success": False, "error": str(e)}

    def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.log_buffer)[-limit:]
