#!/bin/sh
# Ajusta o dono do volume de dados e roda o Copiloto como usuário sem privilégios.
# (Bind mounts criados pelo Docker/Coolify nascem como root; sem isto o SQLite não consegue gravar.)
set -e
DATA_DIR="${COPILOTO_DATA_DIR:-/data}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R copiloto:copiloto "$DATA_DIR" 2>/dev/null || echo "Aviso: não foi possível ajustar o dono de $DATA_DIR"
  export HOME=/home/copiloto
  exec setpriv --reuid=copiloto --regid=copiloto --init-groups "$@"
fi
exec "$@"
