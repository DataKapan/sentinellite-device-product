# Sentinel Operations Runbook

## Hızlı Referans

### Servis Komutları
 ⁠bash
sudo systemctl status sentinel     # Durum
sudo systemctl restart sentinel    # Yeniden başlat
sudo systemctl stop sentinel       # Durdur
sudo journalctl -u sentinel -f     # Canlı log


⁠ ---

## Sorun Giderme

### 1. Cihaz Offline

**Belirtiler:** Pushover bildirimi yok, health.json eski

**Kontrol:**
 ⁠bash
ping <cihaz_ip>
ssh sentinellite-tampere@<cihaz_ip>


⁠ **Çözüm:**
1. Güç kablosunu kontrol et
2. WiFi bağlantısını kontrol et: `iwconfig wlan0`
3. Router'ı yeniden başlat
4. Fiziksel erişim gerekebilir

---

### 2. Upload Başarısız

**Belirtiler:** `failed_count` artıyor, `temp/failed/` dolu

**Kontrol:**
 ⁠bash
ls ~/sentinel/temp/failed/
cat ~/sentinel/health.json | grep failed
sudo journalctl -u sentinel | grep -i ftp | tail -10


⁠ **Çözüm:**
1. FTP sunucusu çalışıyor mu? `ping <ftp_server>`
2. Credentials doğru mu? `sudo cat /etc/sentinel.env`
3. Disk dolu mu? `df -h`
4. Manuel upload dene: `ftp <server>`

---

### 3. Pushover Gitmiyor

**Belirtiler:** Detection var ama bildirim yok

**Kontrol:**
 ⁠bash
tail ~/sentinel/push_log/push_$(date +%Y%m%d).jsonl
sudo journalctl -u sentinel | grep -i pushover | tail -5


⁠ **Çözüm:**
1. Internet var mı? `ping 8.8.8.8`
2. Token doğru mu? `sudo cat /etc/sentinel.env | grep PUSHOVER`
3. Pushover limiti aşıldı mı? (7500/ay)
4. pushover.net'ten token yenile

---

### 4. Disk Dolu

**Belirtiler:** Yazma hataları, servis crash

**Kontrol:**

 ⁠bash
df -h
du -sh ~/sentinel/*


⁠ **Çözüm:**
 ⁠bash
# Eski case'leri temizle
rm -rf ~/sentinel/temp/failed/case_2026040*
# Eski logları temizle
rm ~/sentinel/logs/sentinel.log.*
# Eski event'leri temizle
gzip ~/sentinel/events/events_2026040*.jsonl


⁠ ---

### 5. Kamera Stream Yok

**Belirtiler:** `Frame stale` hatası, detection yok

**Kontrol:**
 ⁠bash
ls -la /dev/shm/sentinel/frame.jpg
ps aux | grep rpicam


⁠ **Çözüm:**
1. Kamera kablosu takılı mı?
2. rpicam-still çalışıyor mu?
3. Servisi restart: `sudo systemctl restart sentinel`
4. Kamerayı test: `rpicam-still -o test.jpg`

---

### 6. Self-Test Başarısız

**Kontrol:**
 ⁠bash
python3 ~/sentinel/main.py --self-test
cat ~/sentinel/self_test_report.json


⁠ **Çözüm:** Başarısız olan teste göre yukarıdaki ilgili bölüme bak.

---

### 7. Log Nereden Bakılır

 ⁠bash
# Sistem logu (journald)
sudo journalctl -u sentinel -n 100 --no-pager

# Uygulama logu
tail -100 ~/sentinel/logs/sentinel.log

# Event logu
tail ~/sentinel/events/events_$(date +%Y%m%d).jsonl

# Push logu
tail ~/sentinel/push_log/push_$(date +%Y%m%d).jsonl

# Health snapshot
cat ~/sentinel/health.json


⁠ ---

## Rutin Bakım

### Günlük
- [ ] health.json kontrol (uptime, failed_count)
- [ ] Pushover bildirimleri geliyor mu?

### Haftalık
- [ ] Disk kullanımı: `df -h`
- [ ] Failed uploads: `ls ~/sentinel/temp/failed/`
- [ ] Memory trend (health.json'dan)

### Aylık
- [ ] Log rotation çalışıyor mu?
- [ ] Eski event'ler arşivleniyor mu?
- [ ] Secret rotation gerekli mi?

---

## Acil Durum

### Servis Çöktü ve Kalkmıyor
 ⁠bash
sudo systemctl stop sentinel
cd ~/sentinel
python3 -m py_compile main.py  # Syntax hatası?
python3 main.py --self-test    # Neyin eksik?
sudo journalctl -u sentinel -n 50  # Son hatalar


⁠ ### Rollback Gerekli
 ⁠bash
cd ~/sentinel
./scripts/rollback.sh
# veya manuel:
git checkout v3.12-field-ready
sudo systemctl restart sentinel


---

## İletişim

- **Teknik Destek:** orhan@datatrap.fi
- **Acil:** [Telefon numarası]
