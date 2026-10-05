"""
Previsão com Google TimesFM carregada só quando pedida (em segundo plano).

O modelo (torch + timesfm, ~200M parâmetros) é opcional: instale requirements-lab.txt.
Sem ele, a previsão usa uma extrapolação estatística simples — e a tela avisa isso.
"""
import importlib.util
import threading
from typing import Any, Dict, Optional

_lock = threading.Lock()
_state: Dict[str, Any] = {"state": "idle", "error": None, "predictor": None}


def installed() -> bool:
    return importlib.util.find_spec("timesfm") is not None and importlib.util.find_spec("torch") is not None


def status() -> Dict[str, Any]:
    pred = _state["predictor"]
    return {
        "installed": installed(),
        "state": _state["state"],
        "error": _state["error"],
        "model_loaded": bool(pred is not None and getattr(pred, "model", None) is not None),
    }


def _load() -> None:
    try:
        from src.lab.timesfm_predictor import TimesFMPredictor

        pred = TimesFMPredictor.get_instance()
        with _lock:
            _state.update(predictor=pred, state="ready", error=None if pred.model is not None else "TimesFM não carregou — usando extrapolação estatística")
    except Exception as exc:  # pragma: no cover - depende do ambiente
        with _lock:
            _state.update(state="error", error=str(exc))


def ensure_loading() -> Dict[str, Any]:
    with _lock:
        if _state["state"] in ("idle", "error"):
            _state.update(state="loading", error=None)
            threading.Thread(target=_load, name="timesfm-loader", daemon=True).start()
    return status()


def predict(signal: Dict[str, Any], horizon: int = 15) -> Optional[Dict[str, Any]]:
    pred = _state["predictor"]
    if _state["state"] != "ready" or pred is None:
        return None
    trade = {
        "ticker": signal.get("ticker"),
        "lado": signal.get("lado"),
        "strike": signal.get("strike"),
        "opcao_tipo": signal.get("opcao_tipo"),
        "underlying": signal.get("underlying"),
        "preco_entrada": signal.get("preco_entrada"),
    }
    return pred.predict_trade_success(trade, horizon_days=max(5, min(int(horizon), 30)))
