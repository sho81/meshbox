#!/bin/bash
# SPDX-License-Identifier: MIT

# Holt das 1. Argument. Wenn es leer ist, wird "ttyUSB0" als Default gesetzt.
DEVICE="${1:-ttyUSB0}"

# Sicherheitsprüfung: Verhindert Pfad-Manipulationen (z. B. "../")
DEVICE=$(basename "$DEVICE")

cd /opt/venvs/meshcore-venv/ || exit 1
source bin/activate

# Führt den Befehl mit dem sicheren Pfad unter /dev/ aus
meshcli -rs "/dev/$DEVICE"

deactivate

