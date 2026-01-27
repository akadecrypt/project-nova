#!/bin/bash
#############################################
# NOVA - Start Server Script
# Starts both backend and frontend servers
#############################################

set -e

# Configuration
BACKEND_PORT=9360
FRONTEND_PORT=8888
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${PURPLE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║     🚀 NOVA - Nutanix Objects Virtual Assistant 🚀        ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i:$port >/dev/null 2>&1 || netstat -tuln 2>/dev/null | grep -q ":$port "; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to find free port
find_free_port() {
    local start_port=$1
    local port=$start_port
    while check_port $port; do
        echo -e "${YELLOW}⚠️  Port $port is in use, trying next...${NC}"
        port=$((port + 1))
        if [ $port -gt $((start_port + 100)) ]; then
            echo -e "${RED}❌ Could not find a free port after 100 attempts${NC}"
            exit 1
        fi
    done
    echo $port
}

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down servers...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    echo -e "${GREEN}✅ Servers stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check and find available ports
echo -e "${BLUE}📡 Checking ports...${NC}"

if check_port $BACKEND_PORT; then
    echo -e "${YELLOW}⚠️  Backend port $BACKEND_PORT is in use${NC}"
    BACKEND_PORT=$(find_free_port $BACKEND_PORT)
fi
echo -e "${GREEN}✅ Backend will use port: $BACKEND_PORT${NC}"

if check_port $FRONTEND_PORT; then
    echo -e "${YELLOW}⚠️  Frontend port $FRONTEND_PORT is in use${NC}"
    FRONTEND_PORT=$(find_free_port $FRONTEND_PORT)
fi
echo -e "${GREEN}✅ Frontend will use port: $FRONTEND_PORT${NC}"

# Navigate to project directory
cd "$SCRIPT_DIR"

# Setup Backend
echo -e "\n${BLUE}📦 Setting up backend...${NC}"
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt --quiet 2>/dev/null || pip install -r requirements.txt

# Create data directory
mkdir -p data/chroma

# Start backend server
echo -e "\n${GREEN}🚀 Starting backend server on port $BACKEND_PORT...${NC}"
NOVA_PORT=$BACKEND_PORT python main.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}❌ Backend failed to start${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID)${NC}"

# Start frontend server
cd "$SCRIPT_DIR"
echo -e "\n${GREEN}🌐 Starting frontend server on port $FRONTEND_PORT...${NC}"
python3 -m http.server $FRONTEND_PORT --bind 0.0.0.0 &
FRONTEND_PID=$!

sleep 2

# Check if frontend started successfully
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}❌ Frontend failed to start${NC}"
    cleanup
    exit 1
fi

echo -e "${GREEN}✅ Frontend started (PID: $FRONTEND_PID)${NC}"

# Get server IP
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="localhost"
fi

# Print success message
echo -e "\n${PURPLE}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ NOVA is running!${NC}"
echo -e "${PURPLE}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BLUE}🌐 Frontend:${NC}    http://$SERVER_IP:$FRONTEND_PORT"
echo -e "  ${BLUE}🔧 Backend API:${NC} http://$SERVER_IP:$BACKEND_PORT"
echo -e "  ${BLUE}📖 API Docs:${NC}    http://$SERVER_IP:$BACKEND_PORT/docs"
echo ""
echo -e "  ${YELLOW}📋 Quick Links:${NC}"
echo -e "     • Chat:      http://$SERVER_IP:$FRONTEND_PORT/index.html"
echo -e "     • Settings:  http://$SERVER_IP:$FRONTEND_PORT/settings.html"
echo ""
echo -e "${PURPLE}════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Keep script running
wait
