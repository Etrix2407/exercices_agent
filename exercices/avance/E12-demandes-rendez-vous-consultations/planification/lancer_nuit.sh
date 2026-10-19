#!/bin/sh
# Déclenchement nocturne de lancer_session.py (Linux, macOS), appelé par cron.
# MODE vaut --simulation tant que l'essai réel n'a pas été validé ; remplacer par --reel ensuite.
# cron ne charge pas le profil du shell : la clé est lue dans un fichier réservé à l'utilisateur.

MODE=--simulation
KIT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$KIT/../.venv/bin/python"

[ -f "$HOME/.config/tri-nocturne.env" ] && . "$HOME/.config/tri-nocturne.env"   # export ANTHROPIC_API_KEY=...
cd "$KIT" || exit 1
mkdir -p sorties
"$PYTHON" lancer_session.py $MODE --duree-max 1800 --tokens-max 3000000 --budget-centimes 500 >> sorties/nuit.log 2>&1
