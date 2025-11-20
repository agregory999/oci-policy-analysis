#!/usr/bin/env bash
set -e

echo "==============================================="
echo "            LOCAL CLEAN (FULL RESET)           "
echo "==============================================="

echo "🧹 Removing virtual environment..."
rm -rf .venv

echo "🗑 Removing build artifacts..."
rm -rf dist build wheels frozen.txt deps.txt deps2.txt

echo "🧽 Cleaning Python caches..."
find . -name "__pycache__" -type d -exec rm -rf {} +

echo "✨ Clean complete."
