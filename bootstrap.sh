#!/usr/bin/env bash
# bootstrap.sh — Setup-Einstieg fuer agent-mesh (Leo 2026-09-29: "Bootstrailer fuer alle repos").
# Idempotent: legt nur fehlendes an, kann beliebig oft laufen.
# Startet keinen Dienst, schreibt nichts nach ~/.claude oder systemd.
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
[ -x .venv/bin/python ] || "${PYTHON:-python3}" -m venv .venv
.venv/bin/pip install -q -e .
echo "bootstrap ok: $(pwd)"
