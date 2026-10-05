"""
Ponto de entrada WSGI (Docker/gunicorn):

    gunicorn -w 1 --threads 16 -b 0.0.0.0:5000 wsgi:app

Use UM worker: o monitor de sinais e o feed de cotações rodam como threads dentro do processo.
"""
import logging
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)  # módulos do laboratório usam caminhos relativos à raiz

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from web.app import create_app  # noqa: E402

app = create_app(start_monitor=os.getenv("COPILOTO_NO_MONITOR", "").lower() not in ("1", "true", "yes"))
