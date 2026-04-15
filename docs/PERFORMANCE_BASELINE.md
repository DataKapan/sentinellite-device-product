# Sentinel Performance Baseline

## Test Tarihi: 2026-04-12

## Donanım
- Raspberry Pi Zero 2W
- 512MB RAM
- Standard Camera (1280x720)

## Baseline Metrikleri

| Metrik | Değer | Kabul Edilebilir Aralık |
|--------|-------|-------------------------|
| Inference Time | 290-330ms | <500ms |
| Total Loop | 350-400ms | <600ms |
| Effective FPS | 2.5-2.8 | >2.0 |
| CPU (active) | 50-70% | <90% |
| CPU (idle) | 20-30% | <50% |
| Memory RSS | 75-85MB | <150MB |
| Memory % | 54-58% | <80% |
| Cold Start | ~750ms | <2000ms |

## 24h Soak Test Kriterleri
- Memory drift: <5MB
- CPU saturation: None
- Restarts: 0
- Detection latency: <3s

## Version
- Sentinel: v3.12-prod
- Model: MobileNet SSD v2 (4.4MB)
- TFLite: XNNPACK delegate
