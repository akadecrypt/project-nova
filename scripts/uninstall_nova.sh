#!/bin/bash
#
# NOVA Uninstallation Script
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

NOVA_HOME="${NOVA_HOME:-$HOME/nova}"

echo -e "${YELLOW}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║     NOVA Uninstallation                                   ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Stop services first
if command -v nova &> /dev/null; then
    echo -e "${YELLOW}Stopping NOVA services...${NC}"
    nova stop 2>/dev/null || true
fi

# Remove symlink
if [ -L /usr/local/bin/nova ]; then
    echo -e "${YELLOW}Removing CLI symlink...${NC}"
    sudo rm -f /usr/local/bin/nova
fi

# Ask for confirmation before removing data
echo ""
read -p "Remove NOVA installation directory ($NOVA_HOME)? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing $NOVA_HOME...${NC}"
    sudo rm -rf "$NOVA_HOME"
    echo -e "${GREEN}NOVA has been uninstalled${NC}"
else
    echo -e "${YELLOW}Keeping $NOVA_HOME (data preserved)${NC}"
    echo -e "${GREEN}NOVA CLI removed, but data is preserved${NC}"
fi

echo ""
