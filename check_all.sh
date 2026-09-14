#!/usr/bin/env bash
# ==============================================================================
# GRP-CHAT: 4-System Activation & Complete Health/Route Verification Script
# Activates Sys1 (Load Balancer), Sys2, Sys3, Sys4 (Backends) and verifies all routes.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

pass_count=0
fail_count=0

report_pass() {
    echo -e "  [${GREEN}PASS${NC}] $1"
    pass_count=$((pass_count + 1))
}

report_fail() {
    echo -e "  [${RED}FAIL${NC}] $1"
    fail_count=$((fail_count + 1))
}

echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo -e "${BOLD}${CYAN}   GRP-CHAT: ACTIVATING AND VERIFYING ALL 4 SYSTEMS              ${NC}"
echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo ""

# Step 1: Start the cluster
echo -e "${BOLD}${BLUE}Step 1: Starting all 4 Systems (1 Load Balancer + 3 Backends)...${NC}"
bash "$SCRIPT_DIR/start_cluster.sh"
echo ""

sleep 2

# Detect host IP
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$HOST_IP" ]; then
    HOST_IP="127.0.0.1"
fi

echo -e "${BOLD}${BLUE}Step 2: Checking Direct Backend Health & Performance Metrics...${NC}"

# Check Sys2 (Port 3310)
SYS2_HEALTH=$(curl -s http://127.0.0.1:3310/health || echo "error")
if echo "$SYS2_HEALTH" | grep -q "healthy"; then
    report_pass "Sys2 (Backend 1, Port 3310): Online & Healthy"
else
    report_fail "Sys2 (Backend 1, Port 3310): Offline or unhealthy response: $SYS2_HEALTH"
fi

SYS2_LOAD=$(curl -s http://127.0.0.1:3310/load || echo "error")
if echo "$SYS2_LOAD" | grep -q "cpu_percent"; then
    report_pass "Sys2 (Backend 1, Port 3310): Performance /load metrics responding"
else
    report_fail "Sys2 (Backend 1, Port 3310): Performance metrics /load failed"
fi

# Check Sys3 (Port 3311)
SYS3_HEALTH=$(curl -s http://127.0.0.1:3311/health || echo "error")
if echo "$SYS3_HEALTH" | grep -q "healthy"; then
    report_pass "Sys3 (Backend 2, Port 3311): Online & Healthy"
else
    report_fail "Sys3 (Backend 2, Port 3311): Offline or unhealthy response: $SYS3_HEALTH"
fi

SYS3_LOAD=$(curl -s http://127.0.0.1:3311/load || echo "error")
if echo "$SYS3_LOAD" | grep -q "cpu_percent"; then
    report_pass "Sys3 (Backend 2, Port 3311): Performance /load metrics responding"
else
    report_fail "Sys3 (Backend 2, Port 3311): Performance metrics /load failed"
fi

# Check Sys4 (Port 5312)
SYS4_HEALTH=$(curl -s http://127.0.0.1:5312/health || echo "error")
if echo "$SYS4_HEALTH" | grep -q "healthy"; then
    report_pass "Sys4 (Backend 3, Port 5312): Online & Healthy"
else
    report_fail "Sys4 (Backend 3, Port 5312): Offline or unhealthy response: $SYS4_HEALTH"
fi

SYS4_LOAD=$(curl -s http://127.0.0.1:5312/load || echo "error")
if echo "$SYS4_LOAD" | grep -q "cpu_percent"; then
    report_pass "Sys4 (Backend 3, Port 5312): Performance /load metrics responding"
else
    report_fail "Sys4 (Backend 3, Port 5312): Performance metrics /load failed"
fi

echo ""
echo -e "${BOLD}${BLUE}Step 3: Checking Sys1 (Load Balancer on Port 6000)...${NC}"

# Check Load Balancer Health
LB_HEALTH=$(curl -s http://127.0.0.1:6000/health || echo "error")
if echo "$LB_HEALTH" | grep -q '"healthy_backends": 3'; then
    report_pass "Sys1 (Load Balancer, Port 6000): Healthy with all 3 backends connected"
elif echo "$LB_HEALTH" | grep -q "healthy"; then
    report_pass "Sys1 (Load Balancer, Port 6000): Healthy ($LB_HEALTH)"
else
    report_fail "Sys1 (Load Balancer, Port 6000): Health check failed: $LB_HEALTH"
fi

# Check Load Balancer Diagnostics (/lb-status)
LB_STATUS=$(curl -s http://127.0.0.1:6000/lb-status || echo "error")
if echo "$LB_STATUS" | grep -q "threshold"; then
    report_pass "Sys1 (Load Balancer): Diagnostics endpoint /lb-status active"
else
    report_fail "Sys1 (Load Balancer): Diagnostics /lb-status failed"
fi

echo ""
echo -e "${BOLD}${BLUE}Step 4: Verifying Required API Routes & Deduplication...${NC}"

TEST_ID="check-$(date +%s%N | cut -b1-13)"

# Test Route 1: POST /message (JSON)
MSG_RESP=$(curl -s -X POST http://127.0.0.1:6000/message \
    -H "Content-Type: application/json" \
    -d "{\"client-name\": \"check_bot\", \"msg\": \"Automated check message\", \"id\": \"$TEST_ID\"}")

if echo "$MSG_RESP" | grep -q '"status":"ok"' && echo "$MSG_RESP" | grep -q '"duplicate":false'; then
    report_pass "Required Route POST /message (JSON): Message accepted and stored"
else
    report_fail "Required Route POST /message (JSON) failed: $MSG_RESP"
fi

# Test Deduplication: Same msg_id sent again
DUP_RESP=$(curl -s -X POST http://127.0.0.1:6000/message \
    -H "Content-Type: application/json" \
    -d "{\"client-name\": \"check_bot\", \"msg\": \"Duplicate attempt message\", \"id\": \"$TEST_ID\"}")

if echo "$DUP_RESP" | grep -q '"duplicate":true'; then
    report_pass "Database Deduplication Guarantee: Duplicate ID was detected & rejected idempotently"
else
    report_fail "Database Deduplication check failed: $DUP_RESP"
fi

# Test Route 1 (Form Encoded): POST /message
FORM_RESP=$(curl -s -X POST http://127.0.0.1:6000/message \
    -d "client-name=check_form_bot&msg=Form-encoded check test")

if echo "$FORM_RESP" | grep -q '"status":"ok"'; then
    report_pass "Required Route POST /message (Form-urlencoded): Accepted and stored"
else
    report_fail "Required Route POST /message (Form-urlencoded) failed: $FORM_RESP"
fi

# Test Route 2: GET /feed
FEED_RESP=$(curl -s http://127.0.0.1:6000/feed)

if echo "$FEED_RESP" | grep -q "Automated check message" && echo "$FEED_RESP" | grep -q '"tampered":false'; then
    report_pass "Required Route GET /feed: Messages retrieved, decrypted, and verified untampered"
else
    report_fail "Required Route GET /feed check failed: $(echo "$FEED_RESP" | head -c 200)"
fi

# Test Security: Signature verification in feed
if echo "$FEED_RESP" | grep -q '"signature_valid":true'; then
    report_pass "Security Layer: Digital signatures verified valid in feed"
else
    report_fail "Security Layer: Digital signature verification failed in feed"
fi

echo ""
echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo -e "${BOLD}                     VERIFICATION SUMMARY                        ${NC}"
echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo -e "  Passed Checks: ${GREEN}${pass_count}${NC}"
echo -e "  Failed Checks: ${RED}${fail_count}${NC}"
echo ""

if [ "$fail_count" -eq 0 ]; then
    echo -e "${BOLD}${GREEN}  ALL 4 SYSTEMS AND REQUIRED ROUTES ARE FULLY OPERATIONAL!        ${NC}"
else
    echo -e "${BOLD}${RED}  SOME CHECKS FAILED. Please review the logs above.              ${NC}"
fi

echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo -e "${BOLD}  ACTIVE ENDPOINTS TO ACCESS & SUBMIT:                           ${NC}"
echo -e "  • Load Balancer URL:   ${CYAN}http://${HOST_IP}:6000/${NC}"
echo -e "  • Submit Message:      ${CYAN}POST http://${HOST_IP}:6000/message${NC}"
echo -e "  • Chat Feed:           ${CYAN}GET  http://${HOST_IP}:6000/feed${NC}"
echo -e "  • LB Diagnostics:      ${CYAN}GET  http://${HOST_IP}:6000/lb-status${NC}"
echo -e "  • Cluster Health:      ${CYAN}GET  http://${HOST_IP}:6000/health${NC}"
echo ""
echo -e "  • Backend 1 (Sys2):    http://127.0.0.1:3310/"
echo -e "  • Backend 2 (Sys3):    http://127.0.0.1:3311/"
echo -e "  • Backend 3 (Sys4):    http://127.0.0.1:5312/"
echo -e "${BOLD}${CYAN}==================================================================${NC}"
echo -e "  ${YELLOW}Notice: All 4 systems remain running in the background.${NC}"
echo -e "  To stop all services at any time, run: ${BOLD}bash stop_cluster.sh${NC}"
echo -e "${BOLD}${CYAN}==================================================================${NC}"
