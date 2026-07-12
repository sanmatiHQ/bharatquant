#!/usr/bin/env bash
# Build full NSE universe from public Kite instruments (no creds needed)
set -euo pipefail
cd "$(dirname "$0")/.."
TIER="${1:-main}"
python3.11 -m src.data.universe_builder --tier "$TIER"
echo "Done. Set UNIVERSE=data/universe_full_nse.csv in .env"
