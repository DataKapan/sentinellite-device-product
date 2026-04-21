# Sentinel Production Target

## Hedef
Single device reliable production deployment

## Kapsam İçi
- 7/24 stabil çalışma
- Crash recovery
- Offline data retention
- Observable health
- Secure secrets
- Controlled deployment

## Kapsam Dışı (Bu branch için)
- Fleet management
- Multi-tenancy
- Billing
- MQTT
- Mobile app
- OTA platform
- Central backend

## Versiyon
- Baseline: v3.12-field-ready
- Target: v3.12-production

---

## Güvenlik Notları

### Secret Management
- Tüm secret'lar `/etc/sentinel.env` dosyasında
- Dosya izni: 600 (root only)
- Servis kullanıcısı: non-root

### Transport Security
- **FTP**: Legacy transport (plaintext) - SFTP/HTTPS migration planlanıyor
- **Pushover**: HTTPS ✅
- **Roadmap**: FTP → SFTP veya HTTPS upload (v4.0)

### Secret Rotation
- [ ] FTP credentials rotated
- [ ] Pushover token rotated
- Son rotation tarihi: ____________
