#!/bin/bash
# ==============================================================================
# SCRIPT PARA DETENER SIST-LQ EN LINUX
# ==============================================================================
pkill -f "gunicorn.*app:app"
echo "SIST-LQ ha sido detenido."
