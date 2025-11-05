#!/bin/bash

# Restart Celery Workers Script
# This script stops all Celery workers, clears cache files, and restarts workers

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  Restarting Celery Workers"
echo "=========================================="
echo ""

# Step 1: Stop all Celery worker processes
echo -e "${YELLOW}Step 1: Stopping Celery workers...${NC}"
CELERY_PIDS=$(pgrep -f "celery.*worker" || true)

if [ -z "$CELERY_PIDS" ]; then
    echo -e "  ${GREEN}No Celery workers found running${NC}"
else
    echo -e "  Found Celery worker processes: $CELERY_PIDS"
    pkill -f "celery.*worker" || true
    sleep 2
    
    # Verify they're stopped
    REMAINING=$(pgrep -f "celery.*worker" || true)
    if [ -z "$REMAINING" ]; then
        echo -e "  ${GREEN}All Celery workers stopped successfully${NC}"
    else
        echo -e "  ${RED}Warning: Some processes still running, forcing kill...${NC}"
        pkill -9 -f "celery.*worker" || true
        sleep 1
    fi
fi
echo ""

# Step 2: Clear cache files
echo -e "${YELLOW}Step 2: Clearing cache files...${NC}"

# Clear celery.log
if [ -f "celery.log" ]; then
    > celery.log
    echo -e "  ${GREEN}Cleared celery.log${NC}"
else
    echo -e "  celery.log not found (skipping)${NC}"
fi

# Clear Python __pycache__ directories
echo -e "  Clearing Python cache directories..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
echo -e "  ${GREEN}Cleared Python cache files${NC}"

# Clear Celery beat schedule database (if exists)
if [ -f "celerybeat-schedule" ]; then
    rm -f celerybeat-schedule
    echo -e "  ${GREEN}Cleared celerybeat-schedule${NC}"
fi

if [ -f "celerybeat-schedule.db" ]; then
    rm -f celerybeat-schedule.db
    echo -e "  ${GREEN}Cleared celerybeat-schedule.db${NC}"
fi

echo ""

# Step 3: Wait a moment for cleanup
echo -e "${YELLOW}Step 3: Waiting for cleanup...${NC}"
sleep 2
echo ""

# Step 4: Start Celery workers
echo -e "${YELLOW}Step 4: Starting Celery workers...${NC}"
echo -e "  Command: celery -A app.celery_app worker --loglevel=info -Q files,conversion,parsing,chunking,embedding,celery"
echo ""

# Start Celery worker in background and redirect output to celery.log
nohup celery -A app.celery_app worker \
    --loglevel=info \
    -Q files,conversion,parsing,chunking,embedding,celery \
    > celery.log 2>&1 &

CELERY_PID=$!
echo -e "  ${GREEN}Celery worker started with PID: $CELERY_PID${NC}"
echo ""

# Step 5: Verify workers are running
echo -e "${YELLOW}Step 5: Verifying workers are running...${NC}"
sleep 3

if pgrep -f "celery.*worker" > /dev/null; then
    echo -e "  ${GREEN}Celery workers are running${NC}"
    echo ""
    echo "=========================================="
    echo -e "  ${GREEN}Celery restart completed successfully!${NC}"
    echo "=========================================="
    echo ""
    echo "To check worker status:"
    echo "  python check_celery_workers.py"
    echo ""
    echo "To view logs:"
    echo "  tail -f celery.log"
    echo ""
    exit 0
else
    echo -e "  ${RED}Error: Celery workers failed to start${NC}"
    echo ""
    echo "Check celery.log for errors:"
    echo "  tail -n 50 celery.log"
    echo ""
    exit 1
fi

