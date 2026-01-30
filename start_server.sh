#!/bin/bash

# NOVA Server Startup Script
# Starts SQL Agent, Backend (FastAPI), and Frontend (HTTP server)
# All services bundled together for easy deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SQL_AGENT_PORT=9001
BACKEND_PORT=9360
FRONTEND_PORT=8888
DB_PATH="$HOME/nova.db"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         NOVA Server Startup              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        return 0  # Port in use
    else
        return 1  # Port free
    fi
}

# Function to kill process on port
kill_port() {
    local port=$1
    local pid=$(lsof -ti :$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        echo -e "${YELLOW}Killing existing process on port $port (PID: $pid)${NC}"
        kill -9 $pid 2>/dev/null || true
        sleep 1
    fi
}

# Kill any existing processes on our ports
echo -e "${YELLOW}Checking for existing processes...${NC}"
kill_port $SQL_AGENT_PORT
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT

# Navigate to project directory
cd "$SCRIPT_DIR"

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: Python not found${NC}"
    exit 1
fi

echo -e "${GREEN}Using Python: $($PYTHON_CMD --version)${NC}"

# Install dependencies if needed
if [ -f "backend/requirements.txt" ]; then
    echo -e "${YELLOW}Checking dependencies...${NC}"
    $PYTHON_CMD -m pip install -q -r backend/requirements.txt 2>/dev/null || {
        echo -e "${YELLOW}Installing dependencies...${NC}"
        $PYTHON_CMD -m pip install -r backend/requirements.txt
    }
fi

# ============================================
# Start SQL Agent
# ============================================
echo -e "${GREEN}Starting SQL Agent on port $SQL_AGENT_PORT...${NC}"
cd backend
$PYTHON_CMD sql_agent.py --port $SQL_AGENT_PORT --db "$DB_PATH" > /dev/null 2>&1 &
SQL_AGENT_PID=$!
cd ..

# Wait for SQL Agent to start
echo -e "${YELLOW}Waiting for SQL Agent to initialize...${NC}"
sleep 2

# Check if SQL Agent started successfully
if check_port $SQL_AGENT_PORT; then
    echo -e "${GREEN}✓ SQL Agent started (PID: $SQL_AGENT_PID)${NC}"
    echo -e "${CYAN}  Database: $DB_PATH${NC}"
else
    echo -e "${RED}✗ SQL Agent failed to start${NC}"
    exit 1
fi

# Update config.json to use local SQL Agent
CONFIG_FILE="$SCRIPT_DIR/backend/config.json"
if [ -f "$CONFIG_FILE" ]; then
    # Check if we need to update the SQL agent URL
    CURRENT_URL=$(grep -o '"url"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" | head -1 | grep -o 'http[^"]*' || echo "")
    LOCAL_URL="http://localhost:$SQL_AGENT_PORT/execute"
    
    if [ "$CURRENT_URL" != "$LOCAL_URL" ]; then
        echo -e "${YELLOW}Updating SQL Agent URL in config.json...${NC}"
        # Use sed to update the URL - compatible with both Linux and macOS
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|\"url\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"url\": \"$LOCAL_URL\"|g" "$CONFIG_FILE"
        else
            sed -i "s|\"url\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"url\": \"$LOCAL_URL\"|g" "$CONFIG_FILE"
        fi
        echo -e "${GREEN}✓ Config updated to use local SQL Agent${NC}"
    fi
fi

# ============================================
# Start Backend
# ============================================
echo -e "${GREEN}Starting backend server on port $BACKEND_PORT...${NC}"
cd backend
$PYTHON_CMD run.py > /dev/null 2>&1 &
BACKEND_PID=$!
cd ..

# Wait for backend to start
echo -e "${YELLOW}Waiting for backend to initialize...${NC}"
sleep 3

# Check if backend started successfully
if check_port $BACKEND_PORT; then
    echo -e "${GREEN}✓ Backend started (PID: $BACKEND_PID)${NC}"
else
    echo -e "${RED}✗ Backend failed to start${NC}"
    kill $SQL_AGENT_PID 2>/dev/null || true
    exit 1
fi

# ============================================
# Start Frontend
# ============================================
echo -e "${GREEN}Starting frontend server on port $FRONTEND_PORT...${NC}"
cd frontend
$PYTHON_CMD -m http.server $FRONTEND_PORT > /dev/null 2>&1 &
FRONTEND_PID=$!
cd ..

# Wait for frontend
sleep 2

if check_port $FRONTEND_PORT; then
    echo -e "${GREEN}✓ Frontend started (PID: $FRONTEND_PID)${NC}"
else
    echo -e "${RED}✗ Frontend failed to start${NC}"
    kill $SQL_AGENT_PID 2>/dev/null || true
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

# ============================================
# Display Status
# ============================================
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           ${GREEN}NOVA is running!${BLUE}              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# Try to get local IP
if command -v ipconfig &> /dev/null; then
    # macOS
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "localhost")
elif command -v hostname &> /dev/null; then
    # Linux
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
else
    LOCAL_IP="localhost"
fi

echo -e "${CYAN}Services:${NC}"
echo -e "  SQL Agent:  ${GREEN}http://localhost:$SQL_AGENT_PORT${NC}"
echo -e "  Backend:    ${GREEN}http://$LOCAL_IP:$BACKEND_PORT${NC}"
echo -e "  Frontend:   ${GREEN}http://$LOCAL_IP:$FRONTEND_PORT${NC}"
echo -e "  API Docs:   ${GREEN}http://$LOCAL_IP:$BACKEND_PORT/docs${NC}"
echo ""
echo -e "${CYAN}Database:${NC}"
echo -e "  Path:       ${GREEN}$DB_PATH${NC}"
echo ""

# Check log collection prerequisites
echo -e "${CYAN}Log Collection Status:${NC}"
if command -v sshpass &> /dev/null; then
    echo -e "  sshpass:     ${GREEN}✓ installed${NC}"
    SSHPASS_OK=true
else
    echo -e "  sshpass:     ${YELLOW}✗ not installed (required for auto log collection)${NC}"
    echo -e "               ${YELLOW}Install: brew install hudochenkov/sshpass/sshpass (macOS)${NC}"
    SSHPASS_OK=false
fi

# Check if auto_collect is enabled in config
if [ -f "$SCRIPT_DIR/backend/config.json" ]; then
    AUTO_COLLECT=$(grep -o '"auto_collect"[[:space:]]*:[[:space:]]*\(true\|false\)' "$SCRIPT_DIR/backend/config.json" | grep -o '\(true\|false\)' || echo "false")
    if [ "$AUTO_COLLECT" = "true" ]; then
        echo -e "  auto_collect: ${GREEN}✓ enabled${NC}"
        if [ "$SSHPASS_OK" = true ]; then
            echo -e "  ${GREEN}→ Automated log collection will start after initial delay${NC}"
        else
            echo -e "  ${YELLOW}→ Install sshpass to enable automated log collection${NC}"
        fi
    else
        echo -e "  auto_collect: ${YELLOW}✗ disabled${NC}"
        echo -e "               ${YELLOW}Enable in backend/config.json to auto-collect logs${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Trap Ctrl+C to cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down servers...${NC}"
    kill $SQL_AGENT_PID 2>/dev/null || true
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}All servers stopped${NC}"
    exit 0
}

trap cleanup INT TERM

# Keep script running
wait
