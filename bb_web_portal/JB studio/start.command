#!/bin/bash
# Double-click this file in Finder to start the portal preview.
cd "$(dirname "$0")" || exit 1

if ! command -v node >/dev/null 2>&1; then
    echo "Node.js is required. Install it from https://nodejs.org and try again."
    read -r -p "Press Enter to close."
    exit 1
fi

if [ ! -d node_modules/sass ]; then
    echo "First run: installing the SCSS compiler..."
    npm install --no-fund --no-audit || { read -r -p "Install failed. Press Enter to close."; exit 1; }
fi

PORT="${PORT:-8080}"
(sleep 1 && open "http://localhost:$PORT/") &
PORT="$PORT" node server.js
