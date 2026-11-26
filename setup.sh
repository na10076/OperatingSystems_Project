#!/usr/bin/env bash
# One-time setup: builds the test programs and checks the basics.
set -e
cd "$(dirname "$0")"
make
mkdir -p results
chmod +x run_experiment.py analyze.py check_env.py demo_latency.py live_demo.py 2>/dev/null || true
echo
echo "Built. Now run:  python3 check_env.py"
