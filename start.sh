#!/bin/bash
# ==============================================================================
# SCRIPT DE ARRANQUE Y MONITOREO AUTOMÁTICO PARA SIST-LQ (LINUX)
# ==============================================================================

# 1. Obtener de forma dinámica y absoluta la ruta del proyecto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 2. Crear carpeta de logs si no existe
mkdir -p "$PROJECT_DIR/logs"

# 3. Activar entorno virtual si existe (venv o .venv)
if [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
elif [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# 4. Evitar procesos duplicados (verificar si ya está corriendo)
if pgrep -f "gunicorn.*app:app" > /dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - SIST-LQ ya está en ejecución." >> "$PROJECT_DIR/logs/cron.log"
    exit 0
fi

# 5. Parámetros de ejecución (por defecto puerto 5000 y 3 workers)
PORT="${PORT:-5000}"
WORKERS="${WORKERS:-3}"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Levantando SIST-LQ con Gunicorn en 0.0.0.0:$PORT..." >> "$PROJECT_DIR/logs/cron.log"

# 6. Arrancar Gunicorn en segundo plano
nohup gunicorn \
    --workers "$WORKERS" \
    --bind "0.0.0.0:$PORT" \
    --access-logfile "$PROJECT_DIR/logs/access.log" \
    --error-logfile "$PROJECT_DIR/logs/error.log" \
    app:app > /dev/null 2>&1 &

echo "$(date '+%Y-%m-%d %H:%M:%S') - SIST-LQ levantado exitosamente (PID: $!)." >> "$PROJECT_DIR/logs/cron.log"
