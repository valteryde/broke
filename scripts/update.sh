#!/bin/bash
# Broke server update script
# This script updates the Broke server to the latest version from GitHub

set -e

# Default project directory
PROJECT_DIR="/opt/broke"
KEEP_OLD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --keep-old)
            KEEP_OLD=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --dir DIR     Project directory (default: /opt/broke)"
            echo "  --keep-old    Keep old Docker images (skip cleanup)"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Updating Broke server..."
echo "Project directory: $PROJECT_DIR"

# Generate date tag
DATE_TAG=$(date +"%Y-%m-%d_%H-%M-%S")
NEW_DIR="${PROJECT_DIR}_${DATE_TAG}"

# Step 1: Clone latest code from GitHub
echo ""
echo "1. Cloning latest code from GitHub..."
git clone https://github.com/valteryde/broke.git "$NEW_DIR"
echo "   Cloned to: $NEW_DIR"

# Step 2: Copy data directory if it exists
if [ -d "$PROJECT_DIR/data" ]; then
    echo ""
    echo "2. Copying data directory..."
    cp -r "$PROJECT_DIR/data" "$NEW_DIR/data"
    echo "   Data copied"
fi

# Step 3: Rebuild Docker image
echo ""
echo "3. Rebuilding Docker image..."
cd "$NEW_DIR"
docker compose build --no-cache
echo "   Image built successfully"

# Step 4: Stop old containers
echo ""
echo "4. Stopping old containers..."
cd "$PROJECT_DIR" 2>/dev/null && docker compose down || true

# Step 5: Start new containers
echo ""
echo "5. Starting new containers..."
cd "$NEW_DIR"
docker compose up -d
echo "   Containers started successfully"

# Step 6: Update symlink to point to new version
echo ""
echo "6. Updating symlink..."
rm -f "${PROJECT_DIR}_current"
ln -sf "$NEW_DIR" "${PROJECT_DIR}_current"
echo "   Symlink updated: ${PROJECT_DIR}_current -> $NEW_DIR"

# Step 7: Clean up old images
if [ "$KEEP_OLD" = false ]; then
    echo ""
    echo "7. Cleaning up old images..."
    docker image prune -f
fi

echo ""
echo "✓ Update complete!"
echo "New version: $NEW_DIR"
echo ""
echo "Container status:"
docker compose ps
