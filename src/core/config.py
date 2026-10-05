"""
Configuração do Copiloto.

Dois níveis:
- config/settings.yaml + config/.env: infraestrutura (API do TradingFloors, monitor, flags de execução).
- Tabela `settings` do app.db: preferências do usuário editáveis pela tela Configurações
  (capital, tamanho de posição, analistas seguidos, custos, alertas). Os padrões ficam em DEFAULT_PREFS.
"""
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.getenv("COPILOTO_CONFIG_DIR") or ROOT / "config")
SETTINGS_YAML = CONFIG_DIR / "settings.yaml"
ENV_FILE = CONFIG_DIR / ".env"
# Diretório de dados (banco, notas importadas). No Docker: volume em /data.
DATABASE_DIR = Path(os.getenv("COPILOTO_DATA_DIR") or ROOT / "database")
DEFAULT_DB_PATH = Path(os.getenv("COPILOTO_DB") or DATABASE_DIR / "app.db")

ASSET_CLASSES = ["OPCAO", "ACAO", "FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO", "OUTRO"]

DEFAULT_PREFS: Dict[str, Any] = {
    "capital": {
        "total": 10000.0,
    },
    "sizing": {
        # fixed_capital: valor fixo em R$ por trade | pct_capital: % do capital total por trade
        "mode": "fixed_capital",
        "value_per_trade": 1000.0,
        "pct_per_trade": 10.0,
        "lot_step": 100,
        "max_slippage_pct": 5.0,
    },
    "follow": {
        # Vazio = todos os analistas. Padrão: quem opera opções por dias (copiável à mão).
        # Amilton ficou de fora: ~98% das operações dele em ações abrem e fecham no mesmo dia.
        "traders": ["Sanita", "Ferri", "Artur Horta"],
        "asset_classes": ["OPCAO", "ACAO"],
        # Sinais com entrada mais antiga que isso vão para a caixa de Sinais, não para "Hoje"
        "fresh_hours": 72,
    },
    "costs": {
        "brokerage_per_order": 0.0,
        # Taxas B3 aproximadas (% do volume). Ajuste conforme sua nota de corretagem.
        "b3_fee_pct": {"OPCAO": 0.065, "ACAO": 0.03, "FUTURO": 0.0, "OUTRO": 0.0},
    },
    "alerts": {
        "browser": True,
        "sound": True,
        "telegram": False,
    },
    "broker": {
        "name": "",
        "order_validity": "Dia",
    },
    "execution": {
        # off: só manual | paper: ordens vão para a conta simulada | live: ordens reais no MT5
        "mode": "off",
        "order_type": "limit",
        "auto": {
            "armed": False,
            "entries": True,
            "exits": True,
            "max_orders_per_day": 4,
            "max_daily_loss": 300.0,
            "max_exposure_pct": 60.0,
            "max_trade_value": 1500.0,
            "only_copyable": True,
            "max_signal_age_minutes": 30,
            "cancel_after_minutes": 30,
        },
    },
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def load_yaml() -> Dict[str, Any]:
    if not SETTINGS_YAML.exists():
        return {}
    with open(SETTINGS_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(cfg: Dict[str, Any]) -> None:
    with open(SETTINGS_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_env() -> None:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)


def tf_settings() -> Tuple[str, str, str, str]:
    """(supabase_url, anon_key, email, password) do TradingFloors."""
    load_env()
    tf = load_yaml().get("trading_floors", {})
    return (
        str(tf.get("supabase_url", "")).strip(),
        str(tf.get("supabase_anon_key", "")).strip(),
        os.getenv("TF_EMAIL", "").strip(),
        os.getenv("TF_PASSWORD", "").strip(),
    )


def monitor_poll_seconds() -> int:
    cfg = load_yaml()
    value = cfg.get("monitor", {}).get("poll_seconds") or cfg.get("execution", {}).get("poll_interval_seconds") or 20
    return max(5, int(value))


def _env_bool(name: str) -> Optional[bool]:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return None
    return v.strip().lower() in ("1", "true", "yes", "sim", "on")


def execution_flags() -> Dict[str, Any]:
    """
    Trava de segurança da execução REAL. Só liga com `execution.enabled: true` no settings.yaml
    ou EXECUTION_ENABLED=true no ambiente (Docker). A tela nunca consegue ligar sozinha.
    """
    load_env()
    ex = load_yaml().get("execution", {}) or {}
    env_enabled = _env_bool("EXECUTION_ENABLED")
    enabled = env_enabled if env_enabled is not None else bool(ex.get("enabled", False))
    return {
        "enabled": enabled,
        "dry_run": bool(ex.get("dry_run", True)),
        "broker": (os.getenv("EXECUTION_BROKER") or ex.get("broker") or "mt5_remote").strip(),
        "mt5_agent_url": (os.getenv("MT5_AGENT_URL") or ex.get("mt5_agent_url") or "").strip().rstrip("/"),
        "mt5_agent_token": os.getenv("MT5_AGENT_TOKEN", "").strip(),
        "mt5_terminal_path": (os.getenv("MT5_TERMINAL_PATH") or (load_yaml().get("mt5", {}) or {}).get("terminal_path") or "").strip(),
        "magic_number": int((load_yaml().get("mt5", {}) or {}).get("magic_number", 998877)),
    }


def telegram_credentials() -> Tuple[str, str]:
    load_env()
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------------------------------------------------------------------------
# Preferências do usuário (tabela settings)
# ---------------------------------------------------------------------------

def get_prefs(conn=None) -> Dict[str, Any]:
    from src.core import db

    stored: Dict[str, Any] = {}
    with db.connection(conn) as c:
        for row in c.execute("SELECT key, value FROM settings"):
            try:
                stored[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                continue
    return deep_merge(DEFAULT_PREFS, stored)


def update_prefs(patch: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """Valida e grava apenas as seções conhecidas. Retorna as preferências resultantes."""
    from src.core import db

    current = get_prefs(conn)
    merged = deep_merge(current, {k: v for k, v in (patch or {}).items() if k in DEFAULT_PREFS})
    validated = _validate_prefs(merged)
    with db.transaction(conn) as c:
        for section, value in validated.items():
            c.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (section, json.dumps(value, ensure_ascii=False), now_iso()),
            )
    return validated


def _num(value: Any, default: float, lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _validate_prefs(p: Dict[str, Any]) -> Dict[str, Any]:
    d = DEFAULT_PREFS
    out = copy.deepcopy(p)
    out["capital"]["total"] = _num(p["capital"].get("total"), d["capital"]["total"], 0)

    s = out["sizing"]
    s["mode"] = s.get("mode") if s.get("mode") in ("fixed_capital", "pct_capital") else "fixed_capital"
    s["value_per_trade"] = _num(s.get("value_per_trade"), d["sizing"]["value_per_trade"], 0)
    s["pct_per_trade"] = _num(s.get("pct_per_trade"), d["sizing"]["pct_per_trade"], 0, 100)
    s["lot_step"] = int(_num(s.get("lot_step"), 100, 1))
    s["max_slippage_pct"] = _num(s.get("max_slippage_pct"), d["sizing"]["max_slippage_pct"], 0, 100)

    f = out["follow"]
    f["traders"] = [str(t).strip() for t in (f.get("traders") or []) if str(t).strip()]
    f["asset_classes"] = [a for a in (f.get("asset_classes") or []) if a in ASSET_CLASSES]
    f["fresh_hours"] = int(_num(f.get("fresh_hours"), 72, 1, 24 * 30))

    c = out["costs"]
    c["brokerage_per_order"] = _num(c.get("brokerage_per_order"), 0.0, 0)
    fees = c.get("b3_fee_pct") or {}
    c["b3_fee_pct"] = {k: _num(fees.get(k), d["costs"]["b3_fee_pct"].get(k, 0.0), 0, 5) for k in set(fees) | set(d["costs"]["b3_fee_pct"])}

    a = out["alerts"]
    for k in ("browser", "sound", "telegram"):
        a[k] = bool(a.get(k))

    b = out["broker"]
    b["name"] = str(b.get("name") or "").strip()[:60]
    b["order_validity"] = str(b.get("order_validity") or "Dia").strip()[:30]

    ex = out["execution"]
    ex["mode"] = ex.get("mode") if ex.get("mode") in ("off", "paper", "live") else "off"
    ex["order_type"] = ex.get("order_type") if ex.get("order_type") in ("limit", "market") else "limit"
    au, dau = ex["auto"], d["execution"]["auto"]
    for k in ("armed", "entries", "exits", "only_copyable"):
        au[k] = bool(au.get(k))
    au["max_orders_per_day"] = int(_num(au.get("max_orders_per_day"), dau["max_orders_per_day"], 0, 100))
    au["max_daily_loss"] = _num(au.get("max_daily_loss"), dau["max_daily_loss"], 0)
    au["max_exposure_pct"] = _num(au.get("max_exposure_pct"), dau["max_exposure_pct"], 0, 100)
    au["max_trade_value"] = _num(au.get("max_trade_value"), dau["max_trade_value"], 0)
    au["max_signal_age_minutes"] = int(_num(au.get("max_signal_age_minutes"), dau["max_signal_age_minutes"], 1, 24 * 60))
    au["cancel_after_minutes"] = int(_num(au.get("cancel_after_minutes"), dau["cancel_after_minutes"], 1, 24 * 60))
    if ex["mode"] == "off":
        au["armed"] = False
    return out
