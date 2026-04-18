#!/bin/bash
BACKEND="http://141.144.242.141:8000"
DEVICE_ID=$(cat /etc/sentinel-device-id 2>/dev/null)
CONFIG_FILE="/opt/sentinel/config.json"
VERSION_FILE="/opt/sentinel/.config_version"

if [ -z "$DEVICE_ID" ]; then
    exit 1
fi

CURRENT_VERSION=$(cat "$VERSION_FILE" 2>/dev/null || echo "0")

# Get config and check for commands
curl -s "$BACKEND/api/v1/devices/$DEVICE_ID/config?from_device=true" -o /tmp/new_config.json

# Apply config
python3 /opt/sentinel/scripts/apply_config.py

NEW_VERSION=$(cat "$VERSION_FILE" 2>/dev/null || echo "0")
if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    curl -s -X POST "$BACKEND/api/v1/devices/$DEVICE_ID/config/ack" -H "Content-Type: application/json" -d "{\"version\": $NEW_VERSION}"
    systemctl restart sentinel 2>/dev/null || true
    echo "Config v$NEW_VERSION applied, sentinel restarted"
fi

# Check and execute pending commands
python3 /opt/sentinel/scripts/check_commands.py

# Model sync - check if model changed
python3 /opt/sentinel/model_sync.py 2>/dev/null
