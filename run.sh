#!/bin/bash
cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
    export $(grep -v "^#" .env | xargs)
else
    echo "Error: .env file not found!"
    exit 1
fi

echo "Starting concierge..."
python3 concierge.py
