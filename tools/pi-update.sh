#!/bin/bash
# SPDX-License-Identifier: MIT

# Das Skript bricht sofort ab, wenn ein Befehl fehlschlägt
set -e

echo "========================================"
echo "🔄 1. Paketlisten werden aktualisiert..."
echo "========================================"
sudo apt-get update

echo ""
echo "========================================"
echo "🚀 2. System-Updates werden installiert..."
echo "========================================"
# -y blockiert Rückfragen, --with-new-pkgs erlaubt neue Abhängigkeiten
sudo apt-get upgrade -y --with-new-pkgs

echo ""
echo "========================================"
echo "🧹 3. Nicht mehr benötigte Pakete werden entfernt..."
echo "========================================"
# --purge löscht auch alte Konfigurationsdateien dieser Pakete
sudo apt-get autoremove --purge -y

echo ""
echo "========================================"
echo "🧽 4. Paket-Cache wird bereinigt..."
echo "========================================"
sudo apt-get clean

echo ""
echo "========================================"
echo "✅ Update und Bereinigung erfolgreich abgeschlossen!"
echo "========================================"
