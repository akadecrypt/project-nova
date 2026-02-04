#!/bin/bash
#
# NOVA Installation Script
# Installs NOVA and sets up CLI tools
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NOVA_HOME="${NOVA_HOME:-$HOME/nova}"
NOVA_USER="${NOVA_USER:-$USER}"
NOVA_GROUP="${NOVA_GROUP:-$USER}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║     ███╗   ██╗ ██████╗ ██╗   ██╗ █████╗                   ║"
echo "║     ████╗  ██║██╔═══██╗██║   ██║██╔══██╗                  ║"
echo "║     ██╔██╗ ██║██║   ██║██║   ██║███████║                  ║"
echo "║     ██║╚██╗██║██║   ██║╚██╗ ██╔╝██╔══██║                  ║"
echo "║     ██║ ╚████║╚██████╔╝ ╚████╔╝ ██║  ██║                  ║"
echo "║     ╚═╝  ╚═══╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝                  ║"
echo "║                                                           ║"
echo "║     Nutanix Objects Virtual Assistant                     ║"
echo "║     Installation Script v1.0                              ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
    log_info "Checking dependencies..."
    
    local missing=()
    
    # Check Python 3
    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi
    
    # Check pip
    if ! command -v pip3 &> /dev/null; then
        missing+=("pip3")
    fi
    
    if [ ${#missing[@]} -ne 0 ]; then
        log_error "Missing dependencies: ${missing[*]}"
        log_error "Please install them and run this script again."
        exit 1
    fi
    
    log_info "All dependencies satisfied"
}

create_directories() {
    log_info "Creating NOVA directories..."
    
    # Check if we need sudo (for system directories like /opt)
    if [[ "$NOVA_HOME" == /opt/* ]] || [[ "$NOVA_HOME" == /usr/* ]]; then
        sudo mkdir -p "$NOVA_HOME"
        sudo mkdir -p "$NOVA_HOME/backend"
        sudo mkdir -p "$NOVA_HOME/frontend"
        sudo mkdir -p "$NOVA_HOME/logs"
        sudo mkdir -p "$NOVA_HOME/data"
        sudo mkdir -p "$NOVA_HOME/bin"
        sudo mkdir -p "$NOVA_HOME/run"
        sudo chown -R "$NOVA_USER:$NOVA_GROUP" "$NOVA_HOME"
    else
        mkdir -p "$NOVA_HOME"
        mkdir -p "$NOVA_HOME/backend"
        mkdir -p "$NOVA_HOME/frontend"
        mkdir -p "$NOVA_HOME/logs"
        mkdir -p "$NOVA_HOME/data"
        mkdir -p "$NOVA_HOME/bin"
        mkdir -p "$NOVA_HOME/run"
    fi
    
    log_info "Directories created at $NOVA_HOME"
}

install_files() {
    log_info "Installing NOVA files..."
    
    # Copy backend
    if [ -d "$INSTALL_DIR/backend" ]; then
        cp -r "$INSTALL_DIR/backend/"* "$NOVA_HOME/backend/"
        log_info "Backend installed"
    else
        log_warn "Backend directory not found at $INSTALL_DIR/backend"
    fi
    
    # Copy frontend
    if [ -d "$INSTALL_DIR/frontend" ]; then
        cp -r "$INSTALL_DIR/frontend/"* "$NOVA_HOME/frontend/"
        log_info "Frontend installed"
    else
        log_warn "Frontend directory not found at $INSTALL_DIR/frontend"
    fi
    
    # Copy config if exists
    if [ -f "$INSTALL_DIR/backend/config.json" ]; then
        cp "$INSTALL_DIR/backend/config.json" "$NOVA_HOME/backend/"
    fi
    
    log_info "Files installed to $NOVA_HOME"
}

install_python_deps() {
    log_info "Installing Python dependencies..."
    
    if [ -f "$NOVA_HOME/backend/requirements.txt" ]; then
        pip3 install -r "$NOVA_HOME/backend/requirements.txt" --quiet
        log_info "Python dependencies installed"
    else
        log_warn "requirements.txt not found, skipping Python deps"
    fi
}

create_cli_tool() {
    log_info "Creating NOVA CLI tool..."
    
    # Create the main CLI script
    cat > "$NOVA_HOME/bin/nova" << 'NOVA_CLI'
#!/bin/bash
#
# NOVA CLI - Command Line Interface for NOVA
#

NOVA_HOME="${NOVA_HOME:-$HOME/nova}"
NOVA_PID_DIR="$NOVA_HOME/run"
NOVA_LOG_DIR="$NOVA_HOME/logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Ports
BACKEND_PORT=9360
FRONTEND_PORT=8888
SQL_AGENT_PORT=9001

# Ensure directories exist
mkdir -p "$NOVA_PID_DIR"
mkdir -p "$NOVA_LOG_DIR"

show_banner() {
    echo -e "${CYAN}"
    echo "  _   _  _____  _     _    _    "
    echo " | \ | ||  _  || |   | |  / \   "
    echo " |  \| || | | || |   | | / _ \  "
    echo " | |\  || |_| ||_|   | |/ ___ \ "
    echo " |_| \_||_____|(_)   |_/_/   \_\\"
    echo -e "${NC}"
}

get_pid() {
    local service=$1
    local pid_file="$NOVA_PID_DIR/${service}.pid"
    if [ -f "$pid_file" ]; then
        cat "$pid_file"
    fi
}

is_running() {
    local pid=$1
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

check_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

start_backend() {
    echo -e "${BLUE}Starting NOVA Backend...${NC}"
    
    if check_port $BACKEND_PORT; then
        echo -e "${YELLOW}Backend already running on port $BACKEND_PORT${NC}"
        return 0
    fi
    
    cd "$NOVA_HOME/backend"
    nohup python3 run.py > "$NOVA_LOG_DIR/backend.log" 2>&1 &
    local pid=$!
    echo $pid > "$NOVA_PID_DIR/backend.pid"
    
    # Wait for startup
    sleep 3
    if check_port $BACKEND_PORT; then
        echo -e "${GREEN}✓ Backend started (PID: $pid, Port: $BACKEND_PORT)${NC}"
    else
        echo -e "${RED}✗ Backend failed to start. Check $NOVA_LOG_DIR/backend.log${NC}"
        return 1
    fi
}

start_frontend() {
    echo -e "${BLUE}Starting NOVA Frontend...${NC}"
    
    if check_port $FRONTEND_PORT; then
        echo -e "${YELLOW}Frontend already running on port $FRONTEND_PORT${NC}"
        return 0
    fi
    
    cd "$NOVA_HOME/frontend"
    nohup python3 -m http.server $FRONTEND_PORT > "$NOVA_LOG_DIR/frontend.log" 2>&1 &
    local pid=$!
    echo $pid > "$NOVA_PID_DIR/frontend.pid"
    
    sleep 2
    if check_port $FRONTEND_PORT; then
        echo -e "${GREEN}✓ Frontend started (PID: $pid, Port: $FRONTEND_PORT)${NC}"
    else
        echo -e "${RED}✗ Frontend failed to start. Check $NOVA_LOG_DIR/frontend.log${NC}"
        return 1
    fi
}

start_sql_agent() {
    echo -e "${BLUE}Starting SQL Agent...${NC}"
    
    if check_port $SQL_AGENT_PORT; then
        echo -e "${YELLOW}SQL Agent already running on port $SQL_AGENT_PORT${NC}"
        return 0
    fi
    
    cd "$NOVA_HOME/backend"
    if [ -f "sql_agent.py" ]; then
        nohup python3 sql_agent.py --port $SQL_AGENT_PORT --db "$NOVA_HOME/data/nova.db" > "$NOVA_LOG_DIR/sql_agent.log" 2>&1 &
        local pid=$!
        echo $pid > "$NOVA_PID_DIR/sql_agent.pid"
        
        sleep 2
        if check_port $SQL_AGENT_PORT; then
            echo -e "${GREEN}✓ SQL Agent started (PID: $pid, Port: $SQL_AGENT_PORT)${NC}"
        else
            echo -e "${RED}✗ SQL Agent failed to start. Check $NOVA_LOG_DIR/sql_agent.log${NC}"
            return 1
        fi
    else
        echo -e "${YELLOW}SQL Agent not found, skipping${NC}"
    fi
}

stop_service() {
    local service=$1
    local pid=$(get_pid $service)
    
    if [ -n "$pid" ] && is_running $pid; then
        echo -e "${BLUE}Stopping $service (PID: $pid)...${NC}"
        kill $pid 2>/dev/null
        sleep 1
        if is_running $pid; then
            kill -9 $pid 2>/dev/null
        fi
        rm -f "$NOVA_PID_DIR/${service}.pid"
        echo -e "${GREEN}✓ $service stopped${NC}"
    else
        # Try to find and kill by port
        case $service in
            backend)
                pkill -f "python3.*run.py" 2>/dev/null
                ;;
            frontend)
                pkill -f "python3.*http.server.*$FRONTEND_PORT" 2>/dev/null
                ;;
            sql_agent)
                pkill -f "python3.*sql_agent.py" 2>/dev/null
                ;;
        esac
        rm -f "$NOVA_PID_DIR/${service}.pid"
        echo -e "${YELLOW}$service was not running${NC}"
    fi
}

cmd_start() {
    show_banner
    echo -e "${GREEN}Starting NOVA services...${NC}"
    echo ""
    
    start_sql_agent
    start_backend
    start_frontend
    
    echo ""
    echo -e "${GREEN}NOVA is ready!${NC}"
    echo -e "  Frontend: ${CYAN}http://localhost:$FRONTEND_PORT${NC}"
    echo -e "  Backend:  ${CYAN}http://localhost:$BACKEND_PORT${NC}"
    echo ""
}

cmd_stop() {
    echo -e "${YELLOW}Stopping NOVA services...${NC}"
    echo ""
    
    stop_service frontend
    stop_service backend
    stop_service sql_agent
    
    echo ""
    echo -e "${GREEN}All NOVA services stopped${NC}"
}

cmd_restart() {
    cmd_stop
    echo ""
    sleep 2
    cmd_start
}

cmd_status() {
    show_banner
    echo -e "${BLUE}NOVA Service Status${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Backend status
    if check_port $BACKEND_PORT; then
        local pid=$(lsof -t -i :$BACKEND_PORT 2>/dev/null | head -1)
        echo -e "  Backend     ${GREEN}● Running${NC}  (Port: $BACKEND_PORT, PID: $pid)"
    else
        echo -e "  Backend     ${RED}○ Stopped${NC}"
    fi
    
    # Frontend status
    if check_port $FRONTEND_PORT; then
        local pid=$(lsof -t -i :$FRONTEND_PORT 2>/dev/null | head -1)
        echo -e "  Frontend    ${GREEN}● Running${NC}  (Port: $FRONTEND_PORT, PID: $pid)"
    else
        echo -e "  Frontend    ${RED}○ Stopped${NC}"
    fi
    
    # SQL Agent status
    if check_port $SQL_AGENT_PORT; then
        local pid=$(lsof -t -i :$SQL_AGENT_PORT 2>/dev/null | head -1)
        echo -e "  SQL Agent   ${GREEN}● Running${NC}  (Port: $SQL_AGENT_PORT, PID: $pid)"
    else
        echo -e "  SQL Agent   ${RED}○ Stopped${NC}"
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Show URLs if running
    if check_port $FRONTEND_PORT; then
        echo ""
        echo -e "  ${CYAN}Web UI:${NC}  http://$(hostname -I | awk '{print $1}'):$FRONTEND_PORT"
        echo -e "  ${CYAN}API:${NC}     http://$(hostname -I | awk '{print $1}'):$BACKEND_PORT/docs"
    fi
    echo ""
}

cmd_logs() {
    local service=${1:-all}
    
    case $service in
        backend)
            tail -f "$NOVA_LOG_DIR/backend.log"
            ;;
        frontend)
            tail -f "$NOVA_LOG_DIR/frontend.log"
            ;;
        sql_agent)
            tail -f "$NOVA_LOG_DIR/sql_agent.log"
            ;;
        all)
            tail -f "$NOVA_LOG_DIR"/*.log
            ;;
        *)
            echo "Unknown service: $service"
            echo "Usage: nova logs [backend|frontend|sql_agent|all]"
            ;;
    esac
}

cmd_help() {
    show_banner
    echo "Usage: nova <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start       Start all NOVA services"
    echo "  stop        Stop all NOVA services"
    echo "  restart     Restart all NOVA services"
    echo "  status      Show status of NOVA services"
    echo "  logs        View logs (nova logs [backend|frontend|sql_agent|all])"
    echo "  help        Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  NOVA_HOME   Installation directory (default: /opt/nova)"
    echo ""
    echo "Examples:"
    echo "  nova start      # Start all services"
    echo "  nova status     # Check service status"
    echo "  nova logs backend   # View backend logs"
    echo ""
}

# Main command handler
case "${1:-help}" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs "$2"
        ;;
    help|--help|-h)
        cmd_help
        ;;
    *)
        echo "Unknown command: $1"
        cmd_help
        exit 1
        ;;
esac
NOVA_CLI

    chmod +x "$NOVA_HOME/bin/nova"
    log_info "CLI tool created at $NOVA_HOME/bin/nova"
}

create_symlink() {
    log_info "Setting up nova command..."
    
    # Try to create symlink in /usr/local/bin
    if [ -w /usr/local/bin ]; then
        ln -sf "$NOVA_HOME/bin/nova" /usr/local/bin/nova
        log_info "Symlink created: /usr/local/bin/nova"
    elif sudo -n true 2>/dev/null; then
        # We have passwordless sudo
        sudo ln -sf "$NOVA_HOME/bin/nova" /usr/local/bin/nova
        log_info "Symlink created (with sudo): /usr/local/bin/nova"
    else
        # Add to PATH via shell profile instead
        log_warn "Cannot write to /usr/local/bin, adding to PATH instead"
        
        # Detect shell and profile file
        local shell_profile=""
        if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
            shell_profile="$HOME/.zshrc"
        elif [ -n "$BASH_VERSION" ] || [ "$SHELL" = "/bin/bash" ]; then
            shell_profile="$HOME/.bashrc"
        else
            shell_profile="$HOME/.profile"
        fi
        
        # Add to PATH if not already there
        local path_line="export PATH=\"\$PATH:$NOVA_HOME/bin\""
        if ! grep -q "$NOVA_HOME/bin" "$shell_profile" 2>/dev/null; then
            echo "" >> "$shell_profile"
            echo "# NOVA CLI" >> "$shell_profile"
            echo "$path_line" >> "$shell_profile"
            log_info "Added $NOVA_HOME/bin to PATH in $shell_profile"
            log_warn "Run 'source $shell_profile' or restart your terminal to use 'nova' command"
        else
            log_info "PATH already configured in $shell_profile"
        fi
    fi
}

create_env_file() {
    log_info "Creating environment file..."
    
    cat > "$NOVA_HOME/.env" << EOF
# NOVA Environment Configuration
NOVA_HOME=$NOVA_HOME
NOVA_BACKEND_PORT=9360
NOVA_FRONTEND_PORT=8888
NOVA_SQL_AGENT_PORT=9001
EOF
    
    log_info "Environment file created at $NOVA_HOME/.env"
}

print_success() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}║     NOVA Installation Complete!                           ║${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Installation directory: ${CYAN}$NOVA_HOME${NC}"
    echo ""
    echo -e "Available commands:"
    echo -e "  ${YELLOW}nova start${NC}    - Start all NOVA services"
    echo -e "  ${YELLOW}nova stop${NC}     - Stop all NOVA services"
    echo -e "  ${YELLOW}nova restart${NC}  - Restart all NOVA services"
    echo -e "  ${YELLOW}nova status${NC}   - Show service status"
    echo -e "  ${YELLOW}nova logs${NC}     - View service logs"
    echo -e "  ${YELLOW}nova help${NC}     - Show help"
    echo ""
    echo -e "To start NOVA, run: ${GREEN}nova start${NC}"
    echo ""
}

# Main installation flow
main() {
    echo ""
    log_info "Starting NOVA installation..."
    echo ""
    
    check_dependencies
    create_directories
    install_files
    install_python_deps
    create_cli_tool
    create_symlink
    create_env_file
    
    print_success
}

# Run main
main "$@"
