#!/usr/bin/env bash
# ==============================================================================
# Startup script for GRP-CHAT Dynamic Load Balanced Cluster
# - Starts 3 Backend Workers (Sys2: 3310, Sys3: 3311, Sys4: 5312)
# - Starts Dynamic Go Load Balancer on port 6000
# - Uses Gunicorn + gevent if available (falls back to Python threaded)
# - Fully portable: runs cleanly in any directory or server environment
# ==============================================================================

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR"

# Database & Secret paths (shared among all backends)
export CHAT_DB_PATH="${CHAT_DB_PATH:-$APP_DIR/shared_chat.db}"
export CHAT_SECRET_FILE="${CHAT_SECRET_FILE:-$APP_DIR/secret.key}"

# Find Gunicorn / Python binary
GUNICORN_BIN=""
PYTHON_BIN=""

if [ -f "$APP_DIR/.venv/bin/gunicorn" ]; then
    GUNICORN_BIN="$APP_DIR/.venv/bin/gunicorn"
    PYTHON_BIN="$APP_DIR/.venv/bin/python3"
elif [ -f "$APP_DIR/venv/bin/gunicorn" ]; then
    GUNICORN_BIN="$APP_DIR/venv/bin/gunicorn"
    PYTHON_BIN="$APP_DIR/venv/bin/python3"
elif command -v gunicorn >/dev/null 2>&1; then
    GUNICORN_BIN="$(command -v gunicorn)"
    PYTHON_BIN="$(command -v python3)"
else
    PYTHON_BIN="$(command -v python3 || command -v python)"
fi

echo "=== Stopping any existing processes on ports 6000, 8000, 3310, 3311, 5312 ==="
for port in 6000 8000 3310 3311 5312; do
    lsof -ti:$port 2>/dev/null | xargs -r kill -9 2>/dev/null || true
done
pkill -f "loadbalancer -backends" 2>/dev/null || true
sleep 1

# Ensure Load Balancer binary is built
if [ ! -f "$APP_DIR/loadbalancer" ]; then
    echo "=== Compiling Go Load Balancer ==="
    if command -v go >/dev/null 2>&1; then
        (cd "$APP_DIR" && go build -o "$APP_DIR/loadbalancer" "$APP_DIR/loadbalancer.go")
    else
        echo "[ERROR] 'loadbalancer' binary missing and 'go' compiler not found!"
        exit 1
    fi
fi
chmod +x "$APP_DIR/loadbalancer"

# Backend process runner helper
start_backend() {
    local port="$1"
    local log_file="$LOG_DIR/backend_${port}.log"

    if [ -n "$GUNICORN_BIN" ]; then
        setsid nohup env \
            CHAT_DB_PATH="$CHAT_DB_PATH" \
            CHAT_SECRET_FILE="$CHAT_SECRET_FILE" \
            PORT="$port" \
            "$GUNICORN_BIN" \
            --bind="0.0.0.0:$port" \
            --workers=4 \
            --worker-class="gevent" \
            --worker-connections=2000 \
            --timeout=120 \
            --keep-alive=5 \
            --chdir="$APP_DIR" \
            --access-logfile=- \
            --error-logfile=- \
            --log-level=warning \
            "app:app" \
            < /dev/null >> "$log_file" 2>&1 &
    else
        setsid nohup env \
            CHAT_DB_PATH="$CHAT_DB_PATH" \
            CHAT_SECRET_FILE="$CHAT_SECRET_FILE" \
            PORT="$port" \
            "$PYTHON_BIN" "$APP_DIR/app.py" --port="$port" --host="0.0.0.0" \
            < /dev/null >> "$log_file" 2>&1 &
    fi
    echo $!
}

echo "=== Starting 3 Backends (Ports: 3310, 3311, 5312) ==="
PID_SYS2=$(start_backend 3310)
PID_SYS3=$(start_backend 3311)
PID_SYS4=$(start_backend 5312)
echo "  Sys2 PID: $PID_SYS2 (port 3310)"
echo "  Sys3 PID: $PID_SYS3 (port 3311)"
echo "  Sys4 PID: $PID_SYS4 (port 5312)"

# Wait for backends to initialize
sleep 3

echo "=== Verifying backend health ==="
for port in 3310 3311 5312; do
    if curl -s "http://127.0.0.1:$port/health" | grep -q "healthy"; then
        echo "  [OK] Backend on port $port is HEALTHY"
    else
        echo "  [WARN] Backend on port $port did not respond yet. Checking logs: $LOG_DIR/backend_${port}.log"
    fi
done

echo "=== Starting Dynamic Performance-Based Load Balancer on port 6000 (mirror on 8000) ==="
DEFAULT_BACKENDS="http://127.0.0.1:3310,http://127.0.0.1:3311,http://127.0.0.1:5312"
BACKENDS="${BACKENDS:-$DEFAULT_BACKENDS}"

setsid nohup "$APP_DIR/loadbalancer" \
    -backends="$BACKENDS" \
    -port=6000 \
    -alt-port=8000 \
    -threshold=5 \
    -cpu-threshold=75.0 \
    -health-interval=1s \
    -poll-interval=1s \
    < /dev/null >> "$LOG_DIR/lb.log" 2>&1 &
PID_LB=$!

sleep 2

# Detect host IP
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$HOST_IP" ]; then
    HOST_IP="127.0.0.1"
fi

if curl -s "http://127.0.0.1:6000/health" | grep -q "healthy"; then
    echo "=================================================================="
    echo "  GRP-CHAT Dynamic LB Cluster is RUNNING SUCCESSFULLY!            "
    echo ""
    echo "  🌐 Web Browser URL (Chrome-safe): http://${HOST_IP}:8000/"
    echo "     (Bypasses Chrome's ERR_UNSAFE_PORT restriction on port 6000)"
    echo ""
    echo "  📡 Submission & Evaluator URL:   http://${HOST_IP}:6000/"
    echo "  • Required Route 1:  POST http://${HOST_IP}:6000/message"
    echo "  • Required Route 2:  GET  http://${HOST_IP}:6000/feed"
    echo "  • LB Diagnostics:    GET  http://${HOST_IP}:6000/lb-status"
    echo "  • Health Check:      GET  http://${HOST_IP}:6000/health (or :8000/health)"
    echo ""
    echo "  PIDs: Sys2=$PID_SYS2, Sys3=$PID_SYS3, Sys4=$PID_SYS4, LB=$PID_LB"
    echo "=================================================================="
else
    echo "  [ERROR] Load Balancer not responding. Check $LOG_DIR/lb.log"
    tail -15 "$LOG_DIR/lb.log"
fi
