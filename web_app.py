"""
Copiloto de Trades — servidor web local.

    python web_app.py                 (ou start_web.bat)
    HOST=0.0.0.0 python web_app.py    para acessar pelo celular na mesma rede
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from web.app import create_app, main  # noqa: E402

if __name__ == "__main__":
    main()
