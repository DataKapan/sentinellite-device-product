# Sentinel Ürün Terminolojisi

## Doğru Terminoloji

### Zone Tracking
- ✅ **Doğru:** "Zone occupancy transitions" / "Bölge doluluk geçişleri"
- ❌ **Yanlış:** "Line crossing detection" / "Çizgi geçiş tespiti"

**Açıklama:** Sentinel, bir bölgenin OCCUPIED veya EMPTY durumuna geçişini tespit eder. 
Fiziksel bir çizgiyi geçmeyi izlemez. Bu occupancy-based tracking'dir.

### Hazırlık Seviyeleri

| Seviye | Tanım | Sentinel Durumu |
|--------|-------|-----------------|
| **Pilot-ready** | Kontrollü test ortamında çalışır | ✅ |
| **Single-device production** | Tek cihaz sahada güvenilir çalışır | ✅ (hedef) |
| **Fleet-ready** | 10+ cihaz merkezi yönetimle | ❌ (gelecek) |
| **Enterprise-ready** | 100+ cihaz, multi-tenant | ❌ (gelecek) |

### Tespit Yetenekleri

| Yetenek | Durum | Açıklama |
|---------|-------|----------|
| İnsan tespiti | ✅ | MobileNet SSD, 0.30-0.45 threshold |
| Araç tespiti | ✅ | Kamyon, araba, otobüs |
| Gece modu | ✅ | Adaptive threshold |
| Sayma (counting) | ❌ | Sadece presence, sayım yok |
| Takip (tracking) | ❌ | Frame-to-frame ID yok |
| Yüz tanıma | ❌ | Desteklenmiyor |

### Kullanılacak İfadeler

**Satış/Pazarlama için:**
- "Gerçek zamanlı varlık tespiti" ✅
- "Zone-based güvenlik izleme" ✅
- "Akıllı hareket uyarıları" ✅
- "Edge AI güvenlik sistemi" ✅

**Kullanılmaması gerekenler:**
- "Kişi sayma sistemi" ❌
- "Yüz tanıma" ❌
- "Tracking/takip sistemi" ❌
- "Line crossing detection" ❌

## Teknik vs Pazarlama Uyumu

Her özellik için:
1. Teknik olarak ne yapıyor?
2. Müşteriye nasıl anlatılıyor?
3. Bu ikisi çelişiyor mu?

Çelişki varsa → Pazarlama dilini düzelt, teknik gerçeği değil.
