import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from src.utils import normalize_trader_name

class TradingFloorsClient:
    """
    Cliente de integração com a API do TradingFloors (Supabase REST).
    Gerencia autenticação JWT, expiração de token e consulta de operações.
    """

    def __init__(self, supabase_url: str, supabase_anon_key: str, email: str, password: str, logger=None):
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_anon_key = supabase_anon_key
        self.email = email
        self.password = password
        self.logger = logger
        
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry_timestamp: float = 0.0
        self.user_id: Optional[str] = None

    def _log_info(self, msg: str):
        if self.logger:
            self.logger.info(msg)

    def _log_error(self, msg: str):
        if self.logger:
            self.logger.error(msg)

    def login(self) -> bool:
        """Efetua login com e-mail e senha no Supabase Auth."""
        auth_url = f"{self.supabase_url}/auth/v1/token?grant_type=password"
        headers = {
            "apikey": self.supabase_anon_key,
            "Content-Type": "application/json"
        }
        payload = {
            "email": self.email,
            "password": self.password
        }

        try:
            resp = requests.post(auth_url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                expires_in = data.get("expires_in", 3600)
                self.token_expiry_timestamp = time.time() + expires_in - 120 # renova 2 min antes
                self.user_id = data.get("user", {}).get("id")
                self._log_info(f"Login no TradingFloors bem-sucedido! (User ID: {self.user_id})")
                return True
            else:
                self._log_error(f"Falha no login TradingFloors (HTTP {resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            self._log_error(f"Exceção ao autenticar no TradingFloors: {e}")
            return False

    def ensure_authenticated(self) -> bool:
        """Garante que o token JWT esteja válido ou renova a sessão."""
        if not self.access_token or time.time() >= self.token_expiry_timestamp:
            return self.login()
        return True

    def _get_headers(self) -> Dict[str, str]:
        return {
            "apikey": self.supabase_anon_key,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def fetch_open_trades(self, allowed_products: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Retorna todas as operações com status 'OPEN' na plataforma.
        Mescla dados das tabelas 'trades' e 'opcoes_trades'.
        """
        if not self.ensure_authenticated():
            return []

        trade_map: Dict[tuple, Dict[str, Any]] = {}
        headers = self._get_headers()

        def make_key(item: Dict[str, Any]) -> tuple:
            ticker = (item.get("ticker") or "").strip().upper()
            trader = normalize_trader_name(item.get("trader_nome")).strip().lower()
            lado = (item.get("lado") or "BUY").strip().upper()
            # Agrupa por ticker, analista, lado e data (YYYY-MM-DD), evitando duplicações por pequenas diferenças de minutos
            date_str = str(item.get("timestamp_entrada") or "")[:10]
            return (ticker, trader, lado, date_str)

        # 1. Consulta tabela 'trades'
        try:
            url_trades = f"{self.supabase_url}/rest/v1/trades?status=eq.OPEN&select=*&order=timestamp_entrada.desc"
            resp = requests.get(url_trades, headers=headers, timeout=10)
            if resp.status_code == 200:
                trades_data = resp.json()
                for item in trades_data:
                    item["_source_table"] = "trades"
                    item["trader_nome"] = normalize_trader_name(item.get("trader_nome"))
                    prod = item.get("produto") or "Trading Floor"
                    item["produtos_all"] = [prod]
                    item["produto_display"] = prod
                    k = make_key(item)
                    trade_map[k] = item
            else:
                self._log_error(f"Erro ao consultar 'trades' (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            self._log_error(f"Exceção ao consultar 'trades': {e}")

        # 2. Consulta tabela 'opcoes_trades' e mescla com 'trades' se idêntico
        try:
            url_opcoes = f"{self.supabase_url}/rest/v1/opcoes_trades?status=eq.OPEN&select=*&order=timestamp_entrada.desc"
            resp2 = requests.get(url_opcoes, headers=headers, timeout=10)
            if resp2.status_code == 200:
                opcoes_data = resp2.json()
                for item in opcoes_data:
                    item["trader_nome"] = normalize_trader_name(item.get("trader_nome"))
                    opc_prod = item.get("produto") or "Opções"
                    k = make_key(item)
                    
                    if k in trade_map:
                        # Mescla com registro existente e unifica cotação/dados
                        existing = trade_map[k]
                        item_ts = str(item.get("timestamp_entrada") or "")
                        exist_ts = str(existing.get("timestamp_entrada") or "")

                        # Preserva o preço atual do registro mais recente
                        if item.get("preco_atual") is not None:
                            if existing.get("preco_atual") is None or item_ts > exist_ts:
                                existing["preco_atual"] = item.get("preco_atual")
                        
                        # Preserva o timestamp mais recente
                        if item_ts > exist_ts:
                            existing["timestamp_entrada"] = item.get("timestamp_entrada")

                        if item.get("strike") is not None and not existing.get("strike"):
                            existing["strike"] = item.get("strike")
                        if item.get("opcao_tipo") is not None and not existing.get("opcao_tipo"):
                            existing["opcao_tipo"] = item.get("opcao_tipo")
                        if opc_prod not in existing["produtos_all"]:
                            existing["produtos_all"].append(opc_prod)
                        if "Desafio Eleições" in existing["produtos_all"] and "Opções" in existing["produtos_all"]:
                            existing["produto_display"] = "Desafio Eleições / Opções"
                        existing["tipo_ativo"] = "OPCOES"
                        existing["opcoes_trade_id"] = item.get("id")
                        existing["_source_tables"] = ["trades", "opcoes_trades"]
                    else:
                        item["_source_table"] = "opcoes_trades"
                        item["produto"] = opc_prod
                        item["produtos_all"] = [opc_prod]
                        item["produto_display"] = opc_prod
                        item["tipo_ativo"] = "OPCOES"
                        trade_map[k] = item
            else:
                self._log_error(f"Erro ao consultar 'opcoes_trades' (HTTP {resp2.status_code}): {resp2.text}")
        except Exception as e:
            self._log_error(f"Exceção ao consultar 'opcoes_trades': {e}")


        all_open = list(trade_map.values())

        # Filtra por produtos permitidos se configurado
        if allowed_products:
            filtered = [
                t for t in all_open 
                if any(p in allowed_products for p in t.get("produtos_all", [t.get("produto")])) or 
                ("Opções" in allowed_products and t.get("tipo_ativo") == "OPCOES")
            ]
            return filtered

        return all_open

    def fetch_trade_by_id(self, trade_id: str, source_table: str = "trades") -> Optional[Dict[str, Any]]:
        """Busca o estado atual de um trade específico por ID."""
        if not self.ensure_authenticated():
            return None

        headers = self._get_headers()
        table = source_table if source_table in ["trades", "opcoes_trades"] else "trades"
        url = f"{self.supabase_url}/rest/v1/{table}?id=eq.{trade_id}&select=*"

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    res = data[0]
                    res["_source_table"] = table
                    res["trader_nome"] = normalize_trader_name(res.get("trader_nome"))
                    return res
        except Exception as e:
            self._log_error(f"Exceção ao buscar trade {trade_id}: {e}")

        return None

    def fetch_all_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna histórico recente para visualização e relatórios."""
        if not self.ensure_authenticated():
            return []

        headers = self._get_headers()
        url = f"{self.supabase_url}/rest/v1/trades?select=*&order=timestamp_entrada.desc&limit={limit}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                trades = resp.json()
                for item in trades:
                    item["trader_nome"] = normalize_trader_name(item.get("trader_nome"))
                return trades
        except Exception as e:
            self._log_error(f"Exceção ao buscar histórico recente: {e}")
        return []
