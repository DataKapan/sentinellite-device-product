#!/bin/bash
# Sentinel First Boot Provisioning

MARKER="/etc/sentinel-provisioned"
BACKEND="http://141.144.242.141:8000"

# Zaten provision edilmişse çık
if [ -f "$MARKER" ]; then
    echo "Already provisioned, skipping..."
    exit 0
fi

echo "=== SENTINEL FIRST BOOT PROVISIONING ==="

# 1. Unique Device ID oluştur (xxd yerine od kullan)
MAC=$(cat /sys/class/net/eth0/address 2>/dev/null || cat /sys/class/net/wlan0/address | tr -d ':')
RANDOM_SUFFIX=$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')
DEVICE_ID="sentinel-${MAC: -6}-${RANDOM_SUFFIX}"

echo "Device ID: $DEVICE_ID"

# 2. Hostname değiştir
echo "$DEVICE_ID" | sudo tee /etc/hostname
sudo sed -i "s/127.0.1.1.*/127.0.1.1\t$DEVICE_ID/" /etc/hosts
sudo hostnamectl set-hostname "$DEVICE_ID"

# 3. SSH host key'leri yeniden oluştur
sudo rm -f /etc/ssh/ssh_host_*
sudo dpkg-reconfigure openssh-server -f noninteractive 2>/dev/null || true

# 4. Device ID'yi kaydet
echo "$DEVICE_ID" | sudo tee /etc/sentinel-device-id

# 5. Backend'e register ol
echo "Registering with backend..."
RESULT=$(curl -s -X POST "$BACKEND/api/v1/devices/register" \
    -H "Content-Type: application/json" \
    -d "{\"device_id\": \"$DEVICE_ID\", \"firmware_version\": \"3.12-prod\"}")
echo "Backend response: $RESULT"

# 6. Marker dosyası oluştur
echo "Provisioned at $(date)" | sudo tee "$MARKER"
echo "Device ID: $DEVICE_ID" | sudo tee -a "$MARKER"

echo "=== PROVISIONING COMPLETE ==="
echo "Device ID: $DEVICE_ID"
echo "Rebooting in 5 seconds..."
sleep 5
sudo reboot
