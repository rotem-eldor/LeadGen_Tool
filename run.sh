#!/bin/bash
echo "Starting AI Publishing Dashboard..."

cd "$(dirname "$0")"

if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

echo "Launching dev server..."
npm run dev
