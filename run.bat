@echo off
echo Starting AI Publishing Dashboard...

if not exist "node_modules" (
    echo Installing dependencies...
    npm install
)

echo Launching dev server...
npm run dev
