#!/bin/bash
# Sentinel Telemetry Service

BACKEND="http://141.144.242.141:8000"
DEVICE_ID=$(cat /etc/sentinel-device-id 2>/dev/null)

if [ -z "$DEVICE_ID" ]; then
    echo "Device not provisioned yet"
    exit 1
fi

while true; do
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")
    UPTIME=$(awk '{print int($1)}' /proc/uptime)
    CPU=$(grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print int(usage)}')
    MEM=$(free -m | awk '/Mem:/ {print $3}')
    DISK=$(df -m / | awk 'NR==2 {print $4}')
    
    curl -s -X POST "$BACKEND/api/v1/devices/$DEVICE_ID/telemetry" \
        -H "Content-Type: application/json" \
        -d "{
            \"timestamp\": \"$TIMESTAMP\",
            \"uptime_seconds\": $UPTIME,
            \"mode\": \"WATCHING\",
            \"cpu_percent\": $CPU,
            \"memory_mb\": $MEM,
            \"disk_free_mb\": $DISK,
            \"queue_size\": 0,
            \"failed_count\": 0
        }" > /dev/null 2>&1
    
    sleep 60
done
