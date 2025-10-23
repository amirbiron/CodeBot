#!/bin/bash

# Script to build Code Keeper Bot documentation
# Usage: ./build_docs.sh

set -e

echo "🔨 Building Code Keeper Bot API Documentation..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Sphinx is installed
if ! command -v sphinx-build &> /dev/null; then
    echo -e "${YELLOW}⚠️  Sphinx not found. Installing...${NC}"
    # Install full docs requirements (includes mermaid + MyST)
    pip install --user -r docs/requirements.txt || pip install --break-system-packages -r docs/requirements.txt
    # Add local user bin to PATH for current process if needed
    if [ -d "$HOME/.local/bin" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

# Navigate to docs directory
cd docs

# Clean previous build
echo "🧹 Cleaning previous build..."
rm -rf _build

# Build HTML documentation
echo "📚 Building HTML documentation..."
if ! command -v sphinx-build &> /dev/null; then
    echo -e "${YELLOW}Trying sphinx-build from user bin...${NC}"
fi

"$(command -v sphinx-build)" -b html . _build/html -W --keep-going -q

# Check if build was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Documentation built successfully!${NC}"
    echo -e "${GREEN}📂 Documentation available at: docs/_build/html/index.html${NC}"
    
    # Optional: Open in browser
    if command -v xdg-open &> /dev/null; then
        read -p "Open documentation in browser? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            xdg-open _build/html/index.html
        fi
    fi
else
    echo -e "${RED}❌ Documentation build failed!${NC}"
    exit 1
fi

# Generate API documentation from source (exclude non-module script get-pip.py)
echo "🔄 Updating API documentation..."
# Exclude tests, docs, dotfiles, and get-pip.py which isn't a valid Python module
sphinx-apidoc -o api -f -e -M ../ ../tests ../docs ../get-pip.py ../.* 2>/dev/null || true

echo -e "${GREEN}✨ Documentation generation complete!${NC}"