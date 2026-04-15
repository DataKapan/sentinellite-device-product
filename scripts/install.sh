#!/bin/bash
# Sentinel Installation Script
set -e

echo "=== SENTINEL INSTALLER ==="

# 1. System dependencies
echo "[1/6] Sistem bağımlılıkları..."
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-pil

# 2. Python packages
echo "[2/6] Python paketleri..."
pip3 install httpx psutil ai-edge-litert --break-system-packages

# 3. Create directories
echo "[3/6] Dizinler..."
mkdir -p ~/sentinel/{cases,photos,events,push_log,logs,temp/failed,model}
mkdir -p /dev/shm/sentinel

# 4. Systemd service
echo "[4/6] Systemd servisi..."
sudo cp scripts/sentinel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sentinel

# 5. Secrets template
echo "[5/6] Secrets..."
if [ ! -f /etc/sentinel.env ]; then
    echo "FTP_SERVER=
FTP_USERNAME=
FTP_PASSWORD=
PUSHOVER_APP_TOKEN=
PUSHOVER_GROUP_KEY=" | sudo tee /etc/sentinel.env > /dev/null
    sudo chmod 600 /etc/sentinel.env
    echo "⚠️ /etc/sentinel.env düzenle!"
fi

echo ""
echo "=== KURULUM TAMAMLANDI ==="
echo "1. /etc/sentinel.env düzenle"
echo "2. sudo systemctl start sentinel"
