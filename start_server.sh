#!/bin/bash

# NOVA Server Startup Script
# Starts both backend (FastAPI) and frontend (HTTP server)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKEND_PORT=9360
FRONTEND_PORT=8888
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}       NOVA Server Startup          ${NC}"
echo -e "${BLUE}=====================================${NC}"
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

# Start backend
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
    exit 1
fi

# Start frontend
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
    exit 1
fi

# Get IP addresses
echo ""
echo -e "${BLUE}=====================================${NC}"
echo -e "${GREEN}NOVA is running!${NC}"
echo -e "${BLUE}=====================================${NC}"
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

echo -e "Frontend:  ${GREEN}http://$LOCAL_IP:$FRONTEND_PORT${NC}"
echo -e "Backend:   ${GREEN}http://$LOCAL_IP:$BACKEND_PORT${NC}"
echo -e "API Docs:  ${GREEN}http://$LOCAL_IP:$BACKEND_PORT/docs${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Trap Ctrl+C to cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down servers...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}Servers stopped${NC}"
    exit 0
}

trap cleanup INT TERM

# Keep script running
wait
