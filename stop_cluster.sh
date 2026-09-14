#!/usr/bin/env bash
# ==============================================================================
# Stop script for GRP-CHAT cluster
# Stops all backend instances and load balancer
# ==============================================================================

echo "Stopping GRP-CHAT cluster on ports 6000, 3310, 3311, 5312..."
for port in 6000 3310 3311 5312; do
    lsof -ti:$port 2>/dev/null | xargs -r kill -9 2>/dev/null || true
done
pkill -f "loadbalancer -backends" 2>/dev/null || true
pkill -f "gunicorn.*3310" 2>/dev/null || true
pkill -f "gunicorn.*3311" 2>/dev/null || true
pkill -f "gunicorn.*5312" 2>/dev/null || true
echo "All cluster services stopped."
