#!/bin/bash
cd "$(dirname "$0")"

echo "============================================================"
echo "  HYDRA AI SURVEILLANCE — WEB DASHBOARD"
echo "  Team Code Warriors / Team Hydra"
echo "============================================================"
echo

echo "[1/2] Installing requirements..."
pip install flask opencv-python ultralytics numpy --quiet --break-system-packages 2>/dev/null || \
pip install flask opencv-python ultralytics numpy --quiet

echo "[2/2] Starting Flask server..."
echo
echo "  ✅  Open your browser at: http://localhost:5000"
echo "  ✅  Press Ctrl+C to stop"
echo

python app/app.py
