#!/bin/bash
# Sentinel Rollback Script

echo "=== SENTINEL ROLLBACK ==="

# Stop service
sudo systemctl stop sentinel

# List available versions
echo "Mevcut git tag'ler:"
git tag -l

read -p "Hangi versiyona dönmek istiyorsunuz? (örn: v3.12-field-ready): " VERSION

if git rev-parse "$VERSION" >/dev/null 2>&1; then
    git checkout "$VERSION"
    echo "✅ $VERSION versiyonuna dönüldü"
    sudo systemctl start sentinel
    sleep 3
    systemctl status sentinel --no-pager | head -5
else
    echo "❌ Versiyon bulunamadı: $VERSION"
    exit 1
fi
