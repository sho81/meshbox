#!/bin/bash
# SPDX-License-Identifier: MIT
# meshcli-neighbors.sh - publish the MeshCore repeater neighbor list to /var/www/html.
# Real work is done by mesh-neighbors.py (talks serial directly, no meshcli involved).
# Called every minute from db4sjp's crontab; output goes to /var/log/mesh-neighbors.log.
exec /opt/venvs/meshcore-venv/bin/python /usr/local/bin/mesh-neighbors.py "$@"
