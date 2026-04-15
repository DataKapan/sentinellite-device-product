# Sentinel Deployment Checklist

## Pre-deployment
- [ ] Golden image hazır
- [ ] Config.json cihaza özel düzenlenmiş
- [ ] /etc/sentinel.env secrets dolu

## Installation
- [ ] scripts/install.sh çalıştırıldı
- [ ] Systemd servisi enabled
- [ ] Self-test geçti: `python3 main.py --self-test`

## Verification
- [ ] Servis çalışıyor: `systemctl status sentinel`
- [ ] Kamera stream aktif
- [ ] Pushover test bildirimi alındı
- [ ] health.json oluşuyor

## Post-deployment
- [ ] 1 saat gözlem
- [ ] Detection test (kamera önünden geç)
- [ ] Network kesinti testi (wifi kapat/aç)

## Rollback Prosedürü
1. `sudo systemctl stop sentinel`
2. `cp main.py.backup main.py`
3. `sudo systemctl start sentinel`
4. Sorun devam ederse: `git checkout v3.12-field-ready`
