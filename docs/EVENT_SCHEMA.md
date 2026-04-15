# Sentinel Event Schema v1.0

## Canonical Event Format

Tüm event'ler bu şemaya uyar:

| Field | Type | Açıklama |
|-------|------|----------|
| event_id | string | Unique ID: {type}_{HHMMSS}_{us} |
| timestamp | string | ISO 8601 datetime |
| device_id | string | Cihaz tanımlayıcı |
| location | string | Konum adı |
| event_type | enum | Event türü |
| entity_type | string/null | insan/kamyon/araba |
| confidence | float/null | AI güven skoru (0-1) |
| zone_state | string/null | EMPTY/OCCUPIED |
| duration_seconds | float/null | Kalma süresi |
| photo_ref | string/null | case_id/filename |

## Event Types

| Type | Açıklama |
|------|----------|
| zone_entry | Bölgeye giriş |
| zone_exit | Bölgeden çıkış |
| human_detected | İnsan tespiti |
| vehicle_detected | Araç tespiti |
| system_health | Sağlık snapshot |
| upload_succeeded | Upload başarılı |
| upload_failed | Upload başarısız |

## Entity Types

- insan
- kamyon
- araba

## Storage

- Event Log: ~/sentinel/events/events_YYYYMMDD.jsonl
- Push Log: ~/sentinel/push_log/push_YYYYMMDD.jsonl
- Retention: 7 gün, sonra gzip

## Version
- v1.0 - 2026-04-12 - Initial schema
