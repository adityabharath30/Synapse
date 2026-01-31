#!/bin/bash
# Install/Update the macOS launchd scheduler for RAG device scanning
#
# Usage:
#   ./scripts/install_scheduler.sh          # Install the scheduler
#   ./scripts/install_scheduler.sh uninstall # Remove the scheduler

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# LaunchAgent paths
PLIST_NAME="com.rag.scanner.plist"
PLIST_SOURCE="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "RAG Scanner Scheduler Installer"
echo "=================================="
echo ""

# Handle uninstall
if [ "$1" == "uninstall" ]; then
    echo -e "${YELLOW}Uninstalling scheduler...${NC}"
    
    # Stop the service if running
    if launchctl list | grep -q "com.rag.scanner"; then
        echo "Stopping service..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    
    # Remove the plist
    if [ -f "$PLIST_DEST" ]; then
        rm "$PLIST_DEST"
        echo -e "${GREEN}✓ Scheduler removed${NC}"
    else
        echo "Scheduler was not installed"
    fi
    exit 0
fi

# Check if source plist exists
if [ ! -f "$PLIST_SOURCE" ]; then
    echo -e "${RED}Error: Source plist not found at $PLIST_SOURCE${NC}"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Ensure data directory exists for logs
mkdir -p "$PROJECT_DIR/data"

# Stop existing service if running
if launchctl list | grep -q "com.rag.scanner"; then
    echo "Stopping existing service..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Copy and configure the plist
echo "Installing scheduler..."

# Replace placeholder with actual project path
sed "s|__RAG_PROJECT_PATH__|$PROJECT_DIR|g" "$PLIST_SOURCE" > "$PLIST_DEST"

# Set correct permissions
chmod 644 "$PLIST_DEST"

# Load the service
echo "Starting service..."
launchctl load "$PLIST_DEST"

echo ""
echo -e "${GREEN}✓ Scheduler installed successfully!${NC}"
echo ""
echo "The scanner will run daily at 3:00 AM."
echo ""
echo "Commands:"
echo "  Check status:     launchctl list | grep com.rag.scanner"
echo "  View logs:        tail -f $PROJECT_DIR/data/scanner.log"
echo "  View errors:      tail -f $PROJECT_DIR/data/scanner_error.log"
echo "  Stop service:     launchctl unload $PLIST_DEST"
echo "  Start service:    launchctl load $PLIST_DEST"
echo "  Uninstall:        $0 uninstall"
echo ""
echo "To run a scan immediately:"
echo "  python scripts/watcher.py --scan-now"
