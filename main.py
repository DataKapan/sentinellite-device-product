#!/usr/bin/env python3
"""
Sentinel Security System v3.12 - Production Ready
================================================
- Append-only event logging (no file rewrite)
- Retention policies (7 days auto-cleanup)
- Zone-based entry/exit tracking
- Hardened watchdog (3 consecutive checks)
- FTP retry/backoff with failed cleanup
- Log rotation (10MB x 5)
- Environment variables for secrets
- Debounced night mode
- Grayscale AI for NoIR camera
"""

import os
import logging
from logging.handlers import RotatingFileHandler
import time
import asyncio
import psutil
import json
import shutil
import traceback
import socket
import gzip
from datetime import datetime, timedelta, timezone
from ftplib import FTP
from enum import Enum, auto
from pathlib import Path

# Radar modülü (opsiyonel)
try:
    from radar_reader import RadarReader
    RADAR_AVAILABLE = True
except ImportError:
    RADAR_AVAILABLE = False

import numpy as np
from PIL import Image
import cv2
from ai_edge_litert.interpreter import Interpreter

import RPi.GPIO as GPIO
import httpx

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = '/opt/sentinel'

# COCO class IDs
CLASS_PERSON = 0
CLASS_CAR = 2
CLASS_BUS = 5
CLASS_TRUCK = 7

# ============ TRANSLATIONS ============
TRANSLATIONS = {
    "tr": {
        "system_active": "🟢 Sentinel Aktif",
        "system_active_msg": "Cihaz: {device_id}\nSürüm: {version}\nMod: Production Ready",
        "human_detected": "🚨 İNSAN TESPİT EDİLDİ - {device_id}",
        "human_detected_msg": "Konum: {location}\nSaat: {time}",
        "vehicle_detected": "🚛 ARAÇ TESPİT EDİLDİ - {device_id}",
        "vehicle_detected_msg": "{vehicle_type} tespit edildi\nKonum: {location}\nSaat: {time}",
        "radar_alert": "📡 RADAR UYARI - {device_id}",
        "radar_alert_msg": "Bölge: {zone}\nMesafe: {distance}cm",
    },
    "en": {
        "system_active": "🟢 Sentinel Active",
        "system_active_msg": "Device: {device_id}\nVersion: {version}\nMode: Production Ready",
        "human_detected": "🚨 HUMAN DETECTED - {device_id}",
        "human_detected_msg": "Location: {location}\nTime: {time}",
        "vehicle_detected": "🚛 VEHICLE DETECTED - {device_id}",
        "vehicle_detected_msg": "{vehicle_type} detected\nLocation: {location}\nTime: {time}",
        "radar_alert": "📡 RADAR ALERT - {device_id}",
        "radar_alert_msg": "Zone: {zone}\nDistance: {distance}cm",
    },
    "fi": {
        "system_active": "🟢 Sentinel Aktiivinen",
        "system_active_msg": "Laite: {device_id}\nVersio: {version}\nMode: Production Ready",
        "human_detected": "🚨 HENKILÖ HAVAITTU - {device_id}",
        "human_detected_msg": "Sijainti: {location}\nAika: {time}",
        "vehicle_detected": "🚛 AJONEUVO HAVAITTU - {device_id}",
        "vehicle_detected_msg": "{vehicle_type} havaittu\nSijainti: {location}\nAika: {time}",
        "radar_alert": "📡 TUTKA HÄLYTYS - {device_id}",
        "radar_alert_msg": "Alue: {zone}\nEtäisyys: {distance}cm",
    }
}

def get_text(key, lang="fi", **kwargs):
    text = TRANSLATIONS.get(lang, TRANSLATIONS["fi"]).get(key, key)
    try:
        return text.format(**kwargs)
    except:
        return text

class SystemMode(Enum):
    NORMAL = auto()
    HUMAN_MODE = auto()
    TRUCK_MODE = auto()

class ZoneState(Enum):
    EMPTY = auto()
    OCCUPIED = auto()

LOG_FILE_PATH = os.path.join(BASE_DIR, "logs/sentinel.log")

# ============ LOGGING (ROTATION) ============

def setup_logging(log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    for handler in logging.root.handlers[:]:
        try: handler.close()
        except: pass
        logging.root.removeHandler(handler)
    
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
    ))
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, stream_handler],
        force=True
    )
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

def log(message, level=logging.INFO):
    logging.log(level, message)

# ============ NOIR RENK DÜZELTMESİ ============

def frame_brightness(img):
    arr = np.asarray(img.convert("L"), dtype=np.float32)
    return arr.mean() / 255.0

def correct_noir_pil(img):
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    brightness = frame_brightness(img)
    
    if brightness < 0.20:
        arr = np.clip(arr * 1.25, 0, 1)
        return Image.fromarray((arr * 255).astype(np.uint8))
    
    luma = arr.mean(axis=2)
    q1, q9 = np.quantile(luma, 0.10), np.quantile(luma, 0.90)
    mask = (luma > q1) & (luma < q9)
    
    if mask.sum() > 100:
        means = arr[mask].mean(axis=0)
        gains = means.mean() / (means + 1e-6)
    else:
        gains = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    
    gains *= np.array([0.75, 1.05, 1.20], dtype=np.float32)
    arr *= gains.reshape(1, 1, 3)
    
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    mag = np.clip(r - ((g + b) * 0.5), 0, 1)
    r, g, b = r - 0.4 * mag, g + 0.2 * mag, b + 0.1 * mag
    
    arr = np.stack([r, g, b], axis=2)
    gray_arr = arr.mean(axis=2, keepdims=True)
    arr = np.clip(gray_arr * 0.2 + arr * 0.8, 0, 1)
    
    return Image.fromarray((arr * 255).astype(np.uint8))

def correct_noir_color(image_path):
    """NoIR kamera renk düzeltmesi (gündüz için)"""
    try:
        img = Image.open(image_path).convert("RGB")
        fixed = correct_noir_pil(img)
        fixed.save(image_path, quality=92)
    except Exception as e:
        log(f"NoIR düzeltme hatası: {e}", logging.ERROR)
    return image_path

# ============ EVENT LOGGER (APPEND-ONLY) ============

class EventLogger:
    """
    Append-only event logging with separate push tracking.
    No file rewrites - safer and faster.
    """
    RETENTION_DAYS = 7
    
    def __init__(self, base_dir, device_id="unknown", location="unknown", config=None):
        self.log_dir = os.path.join(base_dir, "events")
        self.push_dir = os.path.join(base_dir, "push_log")
        self.device_id = device_id
        self.config = config or {}
        self.location = location
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.push_dir, exist_ok=True)
    
    def _get_event_file(self):
        return os.path.join(self.log_dir, f"events_{datetime.now().strftime('%Y%m%d')}.jsonl")
    
    def _get_push_file(self):
        return os.path.join(self.push_dir, f"push_{datetime.now().strftime('%Y%m%d')}.jsonl")
    
    def _sanitize_for_json(self, obj):
        """Convert numpy types and sets to JSON-serializable types"""
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._sanitize_for_json(item) for item in obj]
        elif isinstance(obj, set):
            return list(obj)
        elif hasattr(obj, 'item'):  # numpy scalar (bool_, int_, float_)
            return obj.item()
        elif hasattr(obj, 'tolist'):  # numpy array
            return obj.tolist()
        else:
            return obj

    def log_event(self, event_type, details, photo_path=None, case_id=None):
        """Log event - append only, canonical schema v1.0"""
        log(f"📤 Event logging: {event_type}")
        # Sanitize details for JSON serialization
        safe_details = self._sanitize_for_json(details)
        
        # Sync to backend (non-blocking)
        try:
            import threading
            device_id = self.device_id
            event_id = f"{event_type}_{datetime.now().strftime('%H%M%S_%f')}"
            def send_to_backend(dev_id, etype, details, eid):
                try:
                    import requests
                    resp = requests.post(
                        f"http://141.144.242.141:8000/api/v1/devices/{dev_id}/events",
                        json={
                            "event_id": eid,
                            "event_type": etype,
                            "details": details,
                            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                        },
                        timeout=5
                    )
                    log(f"📡 Backend sync: {etype} -> {resp.status_code}")
                except Exception as ex:
                    log(f"❌ Backend sync error: {ex}")
            threading.Thread(target=send_to_backend, args=(device_id, event_type, safe_details, event_id), daemon=True).start()
            
            # Send to webhook if configured
            webhook_url = self.config.get('WEBHOOK', {}).get('URL', '')
            if webhook_url:
                def send_webhook(url, etype, details, eid):
                    try:
                        import requests
                        requests.post(url, json={
                            "event_id": eid,
                            "event_type": etype,
                            "device_id": device_id,
                            "details": details,
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                        }, timeout=5)
                    except: pass
                threading.Thread(target=send_webhook, args=(webhook_url, event_type, safe_details, event_id), daemon=True).start()
        except: pass
        
        # Build photo_ref as case_id/filename
        photo_ref = None
        if photo_path and case_id:
            photo_ref = f"{case_id}/{os.path.basename(photo_path)}"
        elif photo_path:
            photo_ref = os.path.basename(photo_path)
        
        event = {
            "event_id": f"{event_type}_{datetime.now().strftime('%H%M%S_%f')}",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "device_id": self.device_id,
            "location": self.location,
            "event_type": event_type,
            "entity_type": safe_details.get("entity") or safe_details.get("vehicle_type"),
            "confidence": safe_details.get("confidence"),
            "zone_state": safe_details.get("zone_state"),
            "duration_seconds": safe_details.get("duration_seconds"),
            "photo_ref": photo_ref
        }
        try:
            with open(self._get_event_file(), 'a') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
        except Exception as e:
            log(f"Event log hatası: {e}", logging.ERROR)
        return event
    
    def log_push_result(self, event_id, success, error=None):
        """Log push result to separate file - append only"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "event_id": event_id,
            "success": success,
            "error": str(error) if error else None
        }
        try:
            with open(self._get_push_file(), 'a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            log(f"Push log hatası: {e}", logging.ERROR)
    
    def cleanup_old_logs(self):
        """Archive logs older than RETENTION_DAYS"""
        cutoff = datetime.now() - timedelta(days=self.RETENTION_DAYS)
        
        for log_path in [self.log_dir, self.push_dir]:
            try:
                for fn in os.listdir(log_path):
                    if not fn.endswith('.jsonl'):
                        continue
                    
                    fp = os.path.join(log_path, fn)
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                    
                    if mtime < cutoff:
                        # Gzip and remove
                        gz_path = fp + '.gz'
                        try:
                            with open(fp, 'rb') as f_in:
                                with gzip.open(gz_path, 'wb') as f_out:
                                    f_out.writelines(f_in)
                            os.remove(fp)
                            log(f"📦 Log arşivlendi: {fn}")
                        except Exception as gz_err:
                            log(f"Gzip hatası: {gz_err}", logging.ERROR)
                            os.remove(fp)
            except Exception as e:
                log(f"Log cleanup hatası: {e}", logging.ERROR)

# ============ ZONE TRACKER (ENTRY/EXIT) ============

class ZoneTracker:
    """
    Simple zone-based entry/exit tracking.
    Tracks when zone transitions from empty to occupied and vice versa.
    """
    def __init__(self):
        self.state = ZoneState.EMPTY
        self.last_transition_time = 0
        self.current_session_start = 0
        self.current_entity_type = None  # 'insan', 'kamyon', 'araba'
    
    def update(self, has_detection, entity_type=None):
        """
        Update zone state. Returns transition event or None.
        Transitions: EMPTY->OCCUPIED (entry), OCCUPIED->EMPTY (exit)
        """
        now = time.time()
        event = None
        
        if has_detection:
            if self.state == ZoneState.EMPTY:
                # Entry event
                self.state = ZoneState.OCCUPIED
                self.last_transition_time = now
                self.current_session_start = now
                self.current_entity_type = entity_type
                event = {
                    'type': 'entry',
                    'entity': entity_type,
                    'timestamp': datetime.now(timezone.utc).isoformat() + "Z"
                }
                log(f"🚪 ENTRY: {entity_type}")
            else:
                # Update entity type if changed
                if entity_type:
                    self.current_entity_type = entity_type
        else:
            if self.state == ZoneState.OCCUPIED:
                # Exit event
                duration = now - self.current_session_start
                event = {
                    'type': 'exit',
                    'entity': self.current_entity_type,
                    'timestamp': datetime.now(timezone.utc).isoformat() + "Z",
                    'duration_seconds': round(duration, 1)
                }
                log(f"🚪 EXIT: {self.current_entity_type} (süre: {duration:.1f}s)")
                
                self.state = ZoneState.EMPTY
                self.last_transition_time = now
                self.current_entity_type = None
        
        return event
    
    def get_state(self):
        return {
            'state': self.state.name,
            'entity': self.current_entity_type,
            'occupied_since': self.current_session_start if self.state == ZoneState.OCCUPIED else None
        }

# ============ SENSOR READER (GPIO-ONLY) ============

class SensorReader:
    """GPIO-based presence detection only. No UART."""
    def __init__(self, config):
        self.presence_pin = config.get('PRESENCE_GPIO_PIN')
        self.paused = False
        
        if self.presence_pin is not None:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.presence_pin, GPIO.IN)
                log(f"GPIO {self.presence_pin} ayarlandı.")
            except Exception as e:
                log(f"GPIO ayarlanamadı: {e}", logging.ERROR)
                self.presence_pin = None

    def read_presence(self):
        if self.paused or self.presence_pin is None:
            return False
        try:
            return bool(GPIO.input(self.presence_pin))
        except:
            return False

    def pause(self): 
        self.paused = True
    
    def resume(self): 
        self.paused = False
    
    def cleanup(self): 
        pass

# ============ CAMERA MANAGER ============

class CameraManager:
    """Single-stream CCTV camera with RAM disk frame buffer."""
    
    def __init__(self, save_dir, width=1280, height=720):
        self.save_dir = save_dir
        self.width = width
        self.height = height
        os.makedirs(save_dir, exist_ok=True)
        self.is_available = True
        
        self.frame_path = "/dev/shm/sentinel/frame.jpg"
        self.stream_process = None
        self.day_mode = None
        self.night_mode = False
        self.last_frame_time = 0
        self.last_frame_mtime = 0

    def _is_daytime(self):
        return 7 <= datetime.now().hour < 20

    async def start_stream(self):
        if not self.is_available:
            return False

        desired_day = self._is_daytime()
        if self.stream_process and self.stream_process.returncode is None and self.day_mode == desired_day:
            return True

        await self.stop_stream()
        os.makedirs("/dev/shm/sentinel", exist_ok=True)

        shutter, gain = ("6000", "2.5") if desired_day else ("20000", "8")

        cmd = [
            "rpicam-still",
            "-o", self.frame_path,
            "--nopreview",
            "--width", str(self.width),
            "--height", str(self.height),
            "--quality", "92",
            "--gain", gain,
            "--shutter", shutter,
            "--awb", "auto",
            "--timeout", "0",
            "--timelapse", "100"
        ]
        
        if self.night_mode:
            cmd.extend(["--saturation", "0"])
            log("🌙 Gece modu: Grayscale aktif")

        self.stream_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        self.day_mode = desired_day
        log(f"📷 Stream başladı ({self.width}x{self.height}, {'gündüz' if desired_day else 'gece'})")
        await asyncio.sleep(0.3)
        return True

    async def stop_stream(self):
        if self.stream_process and self.stream_process.returncode is None:
            try:
                self.stream_process.terminate()
                await asyncio.wait_for(self.stream_process.wait(), timeout=2)
            except:
                try: self.stream_process.kill()
                except: pass
        self.stream_process = None

    async def restart_stream(self):
        await self.stop_stream()
        await asyncio.sleep(0.3)
        await self.start_stream()

    def is_stream_alive(self):
        """Check if stream process is running"""
        return self.stream_process and self.stream_process.returncode is None

    def is_frame_fresh(self, max_age=30):
        """Check if frame was updated within max_age seconds"""
        try:
            if os.path.exists(self.frame_path):
                mtime = os.path.getmtime(self.frame_path)
                return (time.time() - mtime) < max_age
        except:
            pass
        return False

    async def get_frame(self):
        try:
            await self.start_stream()
            
            if self.day_mode != self._is_daytime():
                await self.start_stream()

            for _ in range(10):
                if os.path.exists(self.frame_path):
                    mtime = os.path.getmtime(self.frame_path)
                    size = os.path.getsize(self.frame_path)
                    if mtime > self.last_frame_mtime and size > 5000:
                        self.last_frame_mtime = mtime
                        self.last_frame_time = time.time()
                        return self.frame_path
                await asyncio.sleep(0.02)
            
            return None
        except Exception as e:
            log(f"Frame hatası: {e}", logging.ERROR)
            return None

    async def capture_photo(self, prefix="img"):
        frame = await self.get_frame()
        if not frame:
            return None
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        photo_path = os.path.join(self.save_dir, f"{prefix}_{timestamp}.jpg")
        shutil.copy2(frame, photo_path)
        return photo_path

    async def cleanup(self):
        await self.stop_stream()

# ============ TFLITE DETECTOR ============

class TFLiteDetector:
    """TensorFlow Lite object detector with adaptive thresholds."""
    
    def __init__(self, model_path, threshold=0.45, human_threshold_day=0.45, 
                 human_threshold_night=0.30, truck_threshold=0.35, car_threshold=0.40):
        self.threshold = threshold
        self.human_threshold_day = human_threshold_day
        self.human_threshold_night = human_threshold_night
        self.truck_threshold = truck_threshold
        self.car_threshold = car_threshold
        self._is_night = False
        self._brightness = 100
        
        self.interpreter = Interpreter(model_path, num_threads=2)
        self.interpreter.allocate_tensors()
        
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.height = self.input_details[0]['shape'][1]
        self.width = self.input_details[0]['shape'][2]
        log(f"AI modeli yüklendi (2 thread, {self.width}x{self.height})")

    def _empty_result(self):
        return {
            'human_count': 0,
            'human_confidence': 0.0,
            'vehicle_count': 0,
            'vehicle_type': None,
            'vehicle_confidence': 0.0,
            'is_night': False,
            'brightness': 100,
            'detected_classes': set()
        }

    async def detect(self, image_path):
        try:
            loop = asyncio.get_running_loop()
            start_total = time.perf_counter()

            def run_inference():
                t0 = time.perf_counter()
                img = cv2.imread(image_path)
                if img is None:
                    return None
                t1 = time.perf_counter()
                
                # Grayscale conversion (removes NoIR pink tint, improves AI accuracy)
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                brightness = np.mean(gray)
                
                # Grayscale → RGB (model expects 3 channels)
                img_rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
                img_resized = cv2.resize(img_rgb, (self.width, self.height), interpolation=cv2.INTER_AREA)
                t2 = time.perf_counter()
                
                input_data = img_resized[np.newaxis, ...]
                self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
                self.interpreter.invoke()
                t3 = time.perf_counter()
                
                scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
                classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
                t4 = time.perf_counter()
                
                return {
                    'scores': scores,
                    'classes': classes,
                    't_read': t1-t0,
                    't_resize': t2-t1,
                    't_infer': t3-t2,
                    't_out': t4-t3,
                    'brightness': brightness
                }

            result = await loop.run_in_executor(None, run_inference)
            if result is None:
                return self._empty_result()
            
            total = time.perf_counter() - start_total
            
            # Adaptive threshold based on brightness
            self._brightness = result['brightness']
            self._is_night = result['brightness'] < 80
            human_threshold = self.human_threshold_night if self._is_night else self.human_threshold_day
            
            log(f"⏱️ read={result['t_read']*1000:.0f}ms infer={result['t_infer']*1000:.0f}ms total={total*1000:.0f}ms bright={result['brightness']:.0f}")

            # Structured result
            results = {
                'human_count': 0,
                'human_confidence': 0.0,
                'vehicle_count': 0,
                'vehicle_type': None,
                'vehicle_confidence': 0.0,
                'is_night': self._is_night,
                'brightness': result['brightness'],
                'detected_classes': set()
            }
            debug = []

            for score, class_id in zip(result['scores'], result['classes']):
                if score > 0.25:
                    debug.append(f"{int(class_id)}:{score:.2f}")
                
                cid = int(class_id)
                if cid == CLASS_PERSON and score > human_threshold:
                    results['human_count'] += 1
                    results['human_confidence'] = max(results['human_confidence'], float(score))
                    results['detected_classes'].add('insan')
                elif cid == CLASS_TRUCK and score > self.truck_threshold:
                    results['vehicle_count'] += 1
                    results['vehicle_type'] = 'kamyon'
                    results['vehicle_confidence'] = max(results['vehicle_confidence'], float(score))
                    results['detected_classes'].add('kamyon')
                elif cid == CLASS_CAR and score > self.car_threshold:
                    results['vehicle_count'] += 1
                    results['vehicle_type'] = 'araba'
                    results['vehicle_confidence'] = max(results['vehicle_confidence'], float(score))
                    results['detected_classes'].add('araba')
                elif cid == CLASS_BUS and score > self.truck_threshold:
                    results['vehicle_count'] += 1
                    results['vehicle_type'] = 'kamyon'
                    results['vehicle_confidence'] = max(results['vehicle_confidence'], float(score))
                    results['detected_classes'].add('kamyon')

            if debug:
                mode_icon = '🌙' if self._is_night else '☀️'
                log(f"🔬 [{','.join(debug[:3])}] {mode_icon}")

            return results
        except Exception as e:
            log(f"Tespit hatası: {e}", logging.ERROR)
            return self._empty_result()

# ============ FTP QUEUE MANAGER ============

class FTPQueueManager:
    """FTP upload with retry/backoff and failed case cleanup."""
    
    MAX_RETRIES = 3
    BACKOFF_BASE = 5  # seconds
    FAILED_RETENTION_DAYS = 7
    MAX_QUEUE_SIZE = 100  # Hard limit to prevent memory issues
    
    def __init__(self, config, device_id, temp_dir, event_logger=None):
        self.event_logger = event_logger
        # Environment variables take priority
        self.server = os.environ.get('FTP_SERVER', config.get('SERVER', ''))
        self.username = os.environ.get('FTP_USERNAME', config.get('USER', config.get('USERNAME', '')))
        self.password = os.environ.get('FTP_PASSWORD', config.get('PASS', config.get('PASSWORD', '')))
        
        self.device_id = device_id
        self.temp_dir = temp_dir
        self.upload_queue = asyncio.Queue()
        self.failed_dir = os.path.join(temp_dir, "failed")
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(self.failed_dir, exist_ok=True)
        
        # Startup'ta mevcut case'leri tara
        self._pending_cases = []
        cases_dir = os.path.join(os.path.dirname(temp_dir), "cases")
        for scan_dir in [cases_dir, self.failed_dir]:
            if os.path.exists(scan_dir):
                for d in os.listdir(scan_dir):
                    if d.startswith('case_'):
                        self._pending_cases.append(os.path.join(scan_dir, d))
        if self._pending_cases:
            log(f"📤 Başlangıçta {len(self._pending_cases)} bekleyen case bulundu")

    def queue_case(self, case_dir):
        if os.path.isdir(case_dir):
            if self.upload_queue.qsize() >= self.MAX_QUEUE_SIZE:
                log(f"⚠️ FTP kuyruk dolu ({self.MAX_QUEUE_SIZE}), eski case siliniyor", logging.WARNING)
                shutil.rmtree(case_dir, ignore_errors=True)
                return False
            self.upload_queue.put_nowait(case_dir)
            log(f"FTP kuyruğa eklendi: {os.path.basename(case_dir)}")
            return True

    async def _upload_case(self, case_dir, retry_count=0):
        if not self.server:
            # No FTP configured, just cleanup local
            shutil.rmtree(case_dir, ignore_errors=True)
            return True
        
        try:
            loop = asyncio.get_running_loop()
            ftp = await loop.run_in_executor(None, self._connect_ftp)
            if not ftp:
                raise Exception("FTP bağlantısı kurulamadı")
            
            case_name = os.path.basename(case_dir)
            remote_path = f"Sentinel/{self.device_id}/{datetime.now().strftime('%d%m%y')}/{case_name}"
            
            await loop.run_in_executor(None, self._ensure_path, ftp, remote_path)
            
            for fn in os.listdir(case_dir):
                fp = os.path.join(case_dir, fn)
                if os.path.isfile(fp):
                    await loop.run_in_executor(None, self._upload_file, ftp, fp, fn)
            
            ftp.quit()
            shutil.rmtree(case_dir, ignore_errors=True)
            log(f"FTP yüklendi: {case_name}")
            if self.event_logger:
                self.event_logger.log_event("upload_succeeded", {"case_id": case_name})
            return True
            
        except Exception as e:
            log(f"FTP hatası (deneme {retry_count+1}/{self.MAX_RETRIES}): {e}", logging.ERROR)
            
            if retry_count < self.MAX_RETRIES - 1:
                wait_time = self.BACKOFF_BASE * (2 ** retry_count)
                log(f"FTP retry: {wait_time}s sonra tekrar denenecek")
                await asyncio.sleep(wait_time)
                return await self._upload_case(case_dir, retry_count + 1)
            else:
                # Move to failed directory
                if self.event_logger:
                    self.event_logger.log_event("upload_failed", {"case_id": os.path.basename(case_dir), "retries": self.MAX_RETRIES})
                try:
                    failed_path = os.path.join(self.failed_dir, os.path.basename(case_dir))
                    if os.path.exists(failed_path):
                        shutil.rmtree(failed_path, ignore_errors=True)
                    shutil.move(case_dir, failed_path)
                    log(f"FTP kalıcı hata - failed klasörüne taşındı: {os.path.basename(case_dir)}", logging.ERROR)
                except Exception as move_err:
                    log(f"Failed klasörüne taşıma hatası: {move_err}", logging.ERROR)
                    shutil.rmtree(case_dir, ignore_errors=True)
                return False

    def _connect_ftp(self):
        try:
            log(f"FTP bağlanıyor: {self.server} / {self.username}")
            ftp = FTP(self.server, timeout=15)
            ftp.login(self.username, self.password)
            log("FTP bağlantı başarılı")
            return ftp
        except Exception as e:
            log(f"FTP bağlantı hatası: {e}", logging.ERROR)
            return None

    def _ensure_path(self, ftp, path):
        for p in path.split('/'):
            if not p: continue
            try: ftp.cwd(p)
            except:
                ftp.mkd(p)
                ftp.cwd(p)
        ftp.cwd('/')

    def _upload_file(self, ftp, local, fn):
        with open(local, 'rb') as f:
            ftp.storbinary(f'STOR {fn}', f)

    def cleanup_failed(self):
        """Remove failed cases older than FAILED_RETENTION_DAYS"""
        cutoff = datetime.now() - timedelta(days=self.FAILED_RETENTION_DAYS)
        try:
            for fn in os.listdir(self.failed_dir):
                fp = os.path.join(self.failed_dir, fn)
                if os.path.isdir(fp):
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                    if mtime < cutoff:
                        shutil.rmtree(fp, ignore_errors=True)
                        log(f"🗑️ Eski failed case silindi: {fn}")
        except Exception as e:
            log(f"Failed cleanup hatası: {e}", logging.ERROR)

    async def process_queue(self):
        # İlk önce pending case'leri işle
        if hasattr(self, '_pending_cases') and self._pending_cases:
            log(f"📤 {len(self._pending_cases)} bekleyen case yükleniyor...")
            for case_dir in self._pending_cases:
                if os.path.isdir(case_dir):
                    await self._upload_case(case_dir)
            self._pending_cases = []
            log("✅ Bekleyen case'ler işlendi")
        
        while True:
            try:
                case_dir = await asyncio.wait_for(self.upload_queue.get(), timeout=60)
                await self._upload_case(case_dir)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log(f"FTP kuyruk hatası: {e}", logging.ERROR)
            await asyncio.sleep(1)

# ============ PUSHOVER CLIENT ============

class PushoverClient:
    """Async Pushover notifications with proper cleanup."""
    
    def __init__(self, config):
        # Environment variables take priority
        self.token = os.environ.get('PUSHOVER_APP_TOKEN', config.get('APP_TOKEN', ''))
        self.user_key = os.environ.get('PUSHOVER_GROUP_KEY', config.get('GROUP_KEY', ''))
        self.enabled = bool(self.token and self.user_key)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) if self.enabled else None

    async def send_alert(self, title, message, photo_path=None, priority=1):
        if not self.enabled:
            return False
        try:
            data = {
                "token": self.token,
                "user": self.user_key,
                "title": title,
                "message": message,
                "priority": priority
            }
            
            if photo_path and os.path.exists(photo_path):
                with open(photo_path, 'rb') as f:
                    files = {'attachment': (os.path.basename(photo_path), f.read(), 'image/jpeg')}
                resp = await self.client.post("https://api.pushover.net/1/messages.json", data=data, files=files)
            else:
                resp = await self.client.post("https://api.pushover.net/1/messages.json", data=data)
            
            return resp.status_code == 200
        except Exception as e:
            log(f"Pushover hatası: {e}", logging.ERROR)
            return False

    async def close(self):
        if self.client:
            await self.client.aclose()

# ============ CASE MANAGER ============

class CaseManager:
    """Manages photo case directories."""
    
    def __init__(self, base_dir, device_id):
        self.base_dir = base_dir
        self.device_id = device_id
        self.current_case = None
        self.cases_dir = os.path.join(base_dir, "cases")
        os.makedirs(self.cases_dir, exist_ok=True)

    def start_case(self, trigger_type):
        case_id = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{trigger_type}"
        case_dir = os.path.join(self.cases_dir, case_id)
        os.makedirs(case_dir, exist_ok=True)
        self.current_case = {'id': case_id, 'dir': case_dir, 'photos': [], 'start_time': time.time()}
        log(f"📁 Vaka: {case_id}")
        return self.current_case

    def add_photo(self, photo_path):
        if self.current_case and photo_path:
            new_path = os.path.join(self.current_case['dir'], os.path.basename(photo_path))
            shutil.copy2(photo_path, new_path)
            self.current_case['photos'].append(new_path)
            try: os.remove(photo_path)
            except: pass
            return new_path
        return None

    def close_case(self):
        case = self.current_case
        self.current_case = None
        if case:
            duration = time.time() - case.get('start_time', time.time())
            log(f"📁 Vaka kapandı: {case['id']} ({len(case['photos'])} foto, {duration:.1f}s)")
        return case

    def discard_case(self):
        if self.current_case:
            shutil.rmtree(self.current_case['dir'], ignore_errors=True)
            self.current_case = None

# ============ INTERNAL WATCHDOG ============


class HealthMonitor:
    """System health monitoring and telemetry"""
    
    def __init__(self, base_dir, device_id, location, version="3.12"):
        self.base_dir = base_dir
        self.device_id = device_id
        self.location = location
        self.version = version
        self.health_file = os.path.join(base_dir, "health.json")
        self.start_time = time.time()
        
        # Counters (24h rolling)
        self.counters = {
            "event_count": 0,
            "alert_count": 0,
            "upload_success": 0,
            "upload_fail": 0
        }
        self.last_detection_at = None
        self.last_upload_at = None
        self.last_frame_time = None
    
    def increment(self, counter_name):
        """Increment a counter"""
        if counter_name in self.counters:
            self.counters[counter_name] += 1
    
    def record_detection(self):
        """Record last detection time"""
        self.last_detection_at = datetime.now(timezone.utc).isoformat() + "Z"
        self.increment("event_count")
    
    def record_alert(self):
        """Record alert sent"""
        self.increment("alert_count")
    
    def record_upload(self, success=True):
        """Record upload result"""
        if success:
            self.increment("upload_success")
            self.last_upload_at = datetime.now(timezone.utc).isoformat() + "Z"
        else:
            self.increment("upload_fail")
    
    def record_frame(self):
        """Record last frame time"""
        self.last_frame_time = time.time()
    
    def get_frame_age(self):
        """Get age of last frame in seconds"""
        if self.last_frame_time:
            return round(time.time() - self.last_frame_time, 1)
        return None
    
    def generate_snapshot(self, mode="NORMAL", queue_size=0, failed_count=0):
        """Generate health snapshot"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "device_id": self.device_id,
                "location": self.location,
                "version": self.version,
                "uptime_seconds": round(time.time() - self.start_time),
                "mode": mode,
                "cpu_percent": cpu_percent,
                "memory_mb": round(memory.used / 1024 / 1024),
                "memory_percent": memory.percent,
                "disk_free_mb": round(disk.free / 1024 / 1024),
                "disk_percent": disk.percent,
                "last_frame_age_sec": self.get_frame_age(),
                "last_detection_at": self.last_detection_at,
                "last_upload_at": self.last_upload_at,
                "queue_size": queue_size,
                "failed_count": failed_count,
                "counters_24h": self.counters.copy()
            }
            return snapshot
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat() + "Z"}
    
    def write_snapshot(self, mode="NORMAL", queue_size=0, failed_count=0):
        """Write health snapshot to file"""
        snapshot = self.generate_snapshot(mode, queue_size, failed_count)
        try:
            with open(self.health_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
            return True
        except Exception as e:
            logging.error(f"Health write failed: {e}")
            return False

class InternalWatchdog:
    """
    Internal health monitoring with debounced checks.
    Requires 3 consecutive failures before taking action.
    """
    
    CHECK_INTERVAL = 60  # seconds
    CONSECUTIVE_FAILURES_REQUIRED = 3
    MIN_FREE_SPACE_MB = 500
    
    def __init__(self, sentinel, base_dir):
        self.sentinel = sentinel
        self.base_dir = base_dir
        self.heartbeat_file = os.path.join(base_dir, "heartbeat")
        self.stream_failure_count = 0
        self.last_cleanup = 0

    async def run(self):
        while True:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL)
                now = time.time()
                
                # Stream health check (debounced)
                if hasattr(self.sentinel, 'camera'):
                    camera = self.sentinel.camera
                    
                    # Check if stream is alive and frame is fresh
                    stream_ok = camera.is_stream_alive() and camera.is_frame_fresh(max_age=30)
                    
                    if not stream_ok:
                        self.stream_failure_count += 1
                        log(f"⚠️ Watchdog: Stream sağlık kontrolü başarısız ({self.stream_failure_count}/{self.CONSECUTIVE_FAILURES_REQUIRED})")
                        
                        if self.stream_failure_count >= self.CONSECUTIVE_FAILURES_REQUIRED:
                            log("⚠️ Watchdog: Stream yeniden başlatılıyor", logging.WARNING)
                            await camera.restart_stream()
                            self.stream_failure_count = 0
                    else:
                        self.stream_failure_count = 0
                
                # Disk usage check (once per hour)
                if now - self.last_cleanup > 3600:
                    self.last_cleanup = now
                    self._check_disk_space()
                    
                    # Cleanup old logs
                    if hasattr(self.sentinel, 'event_logger'):
                        self.sentinel.event_logger.cleanup_old_logs()
                    
                    # Cleanup failed FTP
                    if hasattr(self.sentinel, 'ftp_manager'):
                        self.sentinel.ftp_manager.cleanup_failed()
                
                # Write heartbeat
                try:
                    Path(self.heartbeat_file).write_text(
                        f"{now}\n{datetime.now(timezone.utc).isoformat() + "Z"}\n{self.sentinel.mode.name}"
                    )
                except:
                    pass
                    
            except Exception as e:
                log(f"Watchdog hatası: {e}", logging.ERROR)
    
    def _check_disk_space(self):
        try:
            usage = shutil.disk_usage(self.base_dir)
            free_mb = usage.free / (1024 * 1024)
            
            if free_mb < self.MIN_FREE_SPACE_MB:
                log(f"⚠️ Watchdog: Disk dolu ({free_mb:.0f}MB), eski case'ler siliniyor", logging.WARNING)
                self._cleanup_old_cases()
        except Exception as e:
            log(f"Disk kontrol hatası: {e}", logging.ERROR)
    
    def _cleanup_old_cases(self):
        try:
            cases_dir = os.path.join(self.base_dir, "cases")
            if not os.path.exists(cases_dir):
                return
            
            # Sort by modification time, oldest first
            cases = []
            for c in os.listdir(cases_dir):
                cp = os.path.join(cases_dir, c)
                if os.path.isdir(cp):
                    cases.append((cp, os.path.getmtime(cp)))
            
            cases.sort(key=lambda x: x[1])
            
            # Remove oldest 10 cases
            for cp, _ in cases[:10]:
                shutil.rmtree(cp, ignore_errors=True)
                log(f"🗑️ Eski case silindi: {os.path.basename(cp)}")
        except Exception as e:
            log(f"Case temizleme hatası: {e}", logging.ERROR)

# ============ SENTINEL SYSTEM ============

class SentinelSystem:
    """Main security system controller."""
    
    VERSION = "3.12"
    
    def __init__(self, config):
        self.config = config
        self.system_config = config.get('SYSTEM', {})
        self.detection_config = config.get('DETECTION', {})
        # Use registered device ID from /etc/sentinel-device-id
        try:
            with open('/etc/sentinel-device-id') as f:
                self.device_id = f.read().strip()
        except:
            self.device_id = config.get('DEVICE_ID') or socket.gethostname()
        
        self.photo_dir = os.path.join(BASE_DIR, 'photos')
        self.temp_dir = os.path.join(BASE_DIR, 'temp')
        os.makedirs(self.photo_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Camera settings from config
        camera_config = config.get('CAMERA', {})
        self.camera_type = camera_config.get('TYPE', 'noir')
        self.noir_correction_enabled = camera_config.get('NOIR_CORRECTION', True)
        self.night_mode_grayscale = camera_config.get('NIGHT_MODE_GRAYSCALE', True)
        cam_width = camera_config.get('WIDTH', 1280)
        cam_height = camera_config.get('HEIGHT', 720)
        
        # Initialize components
        model_path = self.system_config.get('MODEL_PATH') or os.path.join(BASE_DIR, self.system_config.get('MODEL_PATH_RELATIVE', 'model/detect.tflite'))
        self.sensor = SensorReader(config.get('SENSOR', {}))
        self.camera = CameraManager(self.photo_dir, width=cam_width, height=cam_height)
        self.detector = TFLiteDetector(
            model_path, 
            threshold=self.detection_config.get('THRESHOLD', 0.45),
            human_threshold_day=self.detection_config.get('HUMAN_THRESHOLD_DAY', 0.45),
            human_threshold_night=self.detection_config.get('HUMAN_THRESHOLD_NIGHT', 0.30),
            truck_threshold=self.detection_config.get('TRUCK_THRESHOLD', 0.35),
            car_threshold=self.detection_config.get('CAR_THRESHOLD', 0.40)
        )
        self.pushover = PushoverClient(config.get('PUSHOVER', {}))
        self.event_logger = EventLogger(BASE_DIR, device_id=self.device_id, location=self.config.get("LOCATION", "unknown"), config=self.config)
        self.ftp_manager = FTPQueueManager(config.get('FTP', {}), self.device_id, self.temp_dir, event_logger=self.event_logger)
        self.case_manager = CaseManager(BASE_DIR, self.device_id)
        self.health_monitor = HealthMonitor(BASE_DIR, self.device_id, self.config.get("LOCATION", "unknown"), version="3.12-prod")
        self.zone_tracker = ZoneTracker()
        
        # Radar mesafe sistemi (opsiyonel)
        self.radar = None
        self.radar_config = config.get("RADAR", {})
        if RADAR_AVAILABLE and self.radar_config.get("ENABLED", False):
            try:
                self.radar = RadarReader(self.radar_config)
                if self.radar.initialize():
                    self.radar.on_zone_change = self._on_radar_zone_change
                    log("📡 Radar mesafe sistemi aktif")
                else:
                    self.radar = None
            except Exception as e:
                log(f"Radar başlatılamadı: {e}", logging.WARNING)
        self.watchdog = InternalWatchdog(self, BASE_DIR)
        
        log(f"📷 Kamera: {self.camera_type} ({cam_width}x{cam_height}), NoIR düzeltme: {self.noir_correction_enabled}")
        
        self.mode = SystemMode.NORMAL
        
        self.consecutive_human = 0
        self.consecutive_truck = 0
        self.consecutive_empty = 0
        self._vehicle_type = 'kamyon'
        
        # Night mode debounce
        self.night_mode_samples = []
        self.NIGHT_MODE_DEBOUNCE = 3
        
        # Config values with defaults
        self.TRUCK_SCAN_INTERVAL = self.detection_config.get('TRUCK_SCAN_INTERVAL', 10)
        self.HUMAN_PHOTO_INTERVAL = self.detection_config.get('HUMAN_PHOTO_INTERVAL', 1.0)
        self.TRUCK_PHOTO_INTERVAL = self.detection_config.get('TRUCK_PHOTO_INTERVAL', 0.25)
        self.CONFIRM_THRESHOLD = self.detection_config.get('CONFIRM_THRESHOLD', 2)
        self.EXIT_THRESHOLD = self.detection_config.get('EXIT_THRESHOLD', 3)
        self.DETECTION_TOLERANCE = self.detection_config.get('DETECTION_TOLERANCE', 1)
        self.MODE_TIMEOUT = self.detection_config.get('MODE_TIMEOUT', 60)
        
        # Config-driven class filtering
        self.enabled_classes = self.config.get('ENABLED_CLASSES', [0, 2, 7])
        self.notifications_config = self.config.get('NOTIFICATIONS', {'person': True, 'truck': True, 'car': True})
        
        # Schedule config
        self.schedule_mode = self.config.get('SCHEDULE_MODE', '24/7')
        self.schedule_start = self.config.get('SCHEDULE_START', '00:00')
        self.schedule_end = self.config.get('SCHEDULE_END', '23:59')
        self.schedule_days = self.config.get('SCHEDULE_DAYS', [1,2,3,4,5,6,7])
        self.MAX_CASE_PHOTOS = self.detection_config.get('MAX_CASE_PHOTOS', 100)
        self.AUTO_CASE_SPLIT_SECONDS = self.detection_config.get('AUTO_CASE_SPLIT_SECONDS', 1800)
        
        # Rate limiting
        self.last_human_photo_saved = 0
        self.last_truck_photo_saved = 0
        self.radar_latch_until = 0

    async def _supervised_task(self, name, coro_func):
        """Run a task with auto-restart on failure"""
        restart_count = 0
        max_restarts = 10
        backoff = 5
        
        while restart_count < max_restarts:
            try:
                logging.info(f"🔄 Task başlatıldı: {name}")
                await coro_func()
            except asyncio.CancelledError:
                logging.info(f"Task iptal edildi: {name}")
                break
            except Exception as e:
                restart_count += 1
                wait_time = min(backoff * restart_count, 60)
                logging.error(f"❌ Task crashed: {name} ({restart_count}/{max_restarts}) - {e}")
                logging.info(f"⏳ {wait_time}s sonra yeniden başlatılacak...")
                await asyncio.sleep(wait_time)
        
        if restart_count >= max_restarts:
            logging.critical(f"🚨 Task kalıcı olarak başarısız: {name}")

    async def initialize(self):
        await self.camera.start_stream()
        # Supervised tasks - auto-restart on crash
        asyncio.create_task(self._supervised_task("ftp_manager", self.ftp_manager.process_queue))
        asyncio.create_task(self._supervised_task("watchdog", self.watchdog.run))
        asyncio.create_task(self._supervised_task("health_snapshot", self.health_snapshot_task))
        
        await self.pushover.send_alert(
            get_text("system_active", self.config.get("LANGUAGE", "fi")),
            get_text("system_active_msg", self.config.get("LANGUAGE", "fi"), device_id=self.device_id, version=self.VERSION),
            priority=0
        )
        log(f"Sentinel v{self.VERSION} başlatıldı - {self.device_id}")
        return True

    def is_scheduled_active(self):
        """Check if system should be active based on schedule"""
        if self.schedule_mode == '24/7':
            return True
        
        now = datetime.now()
        current_day = now.isoweekday()  # 1=Monday, 7=Sunday
        
        if current_day not in self.schedule_days:
            return False
        
        current_time = now.strftime('%H:%M')
        return self.schedule_start <= current_time <= self.schedule_end

    def reset_counters(self):
        self.consecutive_human = 0
        self.consecutive_truck = 0
        self.consecutive_empty = 0

    async def health_snapshot_task(self):
        """Write health snapshot every 60 seconds"""
        while True:
            try:
                await asyncio.sleep(60)
                queue_size = self.ftp_manager.upload_queue.qsize() if hasattr(self.ftp_manager, 'upload_queue') else 0
                failed_dir = os.path.join(BASE_DIR, "temp", "failed")
                failed_count = len(os.listdir(failed_dir)) if os.path.exists(failed_dir) else 0
                self.health_monitor.write_snapshot(
                    mode=self.mode.name if hasattr(self.mode, "name") else str(self.mode),
                    queue_size=queue_size,
                    failed_count=failed_count
                )
                logging.debug("Health snapshot written")
            except Exception as e:
                logging.error(f"Health snapshot error: {e}")
                await asyncio.sleep(60)

    async def _check_night_mode(self, brightness):
        """Debounced night mode transition"""
        is_dark = brightness < 0.25
        self.night_mode_samples.append(is_dark)
        
        if len(self.night_mode_samples) > self.NIGHT_MODE_DEBOUNCE:
            self.night_mode_samples.pop(0)
        
        should_be_night = all(self.night_mode_samples)
        should_be_day = not any(self.night_mode_samples)
        
        if should_be_night and not self.camera.night_mode:
            log(f"🌙 Gece moduna geçiş (debounced)")
            self.camera.night_mode = True
            await self.camera.restart_stream()
        elif should_be_day and self.camera.night_mode:
            log(f"☀️ Gündüz moduna geçiş (debounced)")
            self.camera.night_mode = False
            await self.camera.restart_stream()

    async def take_and_analyze(self):
        photo = await self.camera.capture_photo("scan")
        if not photo:
            return None, self.detector._empty_result()
        
        # Night mode check
        if self.camera_type == 'noir' and self.night_mode_grayscale:
            try:
                img = Image.open(photo).convert("L")
                brightness = np.asarray(img, dtype=np.float32).mean() / 255.0
                await self._check_night_mode(brightness)
            except:
                pass
        
        result = await self.detector.detect(photo)
        return photo, result


    def _on_radar_zone_change(self, old_zone, new_zone, distance):
        """Radar zone değiştiğinde çağrılır - webhook ve ek aksiyonlar"""
        log(f"📡 Radar zone: {old_zone} → {new_zone} ({distance}cm)")
        
        zone_config = self.radar_config.get("ZONES", {}).get(new_zone, {})
        actions = zone_config.get("actions", [])
        
        # Event log
        self.event_logger.log_event("radar_zone_change", {
            "old_zone": old_zone,
            "new_zone": new_zone,
            "distance_cm": distance,
            "actions": actions
        })
        
        # Webhook
        if "webhook" in actions:
            webhook_url = zone_config.get("webhook_url") or self.radar_config.get("WEBHOOK_URL")
            if webhook_url:
                self._send_radar_webhook(webhook_url, new_zone, distance)
        
        # Pushover (fotoğrafsız, dil destekli)
        if "pushover" in actions and self.radar_config.get("PUSHOVER_ENABLED", True):
            import asyncio
            lang = self.config.get("LANGUAGE", "fi")
            title = get_text("radar_alert", lang, device_id=self.device_id)
            msg = get_text("radar_alert_msg", lang, zone=new_zone, distance=distance)
            asyncio.create_task(self.pushover.send_alert(title, msg, priority=0))
    
    def _send_radar_webhook(self, url, zone, distance):
        """Radar webhook gönder"""
        import threading
        import requests
        def send():
            try:
                payload = {
                    "device_id": self.device_id,
                    "event": "radar_zone_change",
                    "zone": zone,
                    "distance_cm": distance,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                }
                requests.post(url, json=payload, timeout=5)
                log(f"📡 Radar webhook sent: {zone}")
            except Exception as e:
                log(f"Radar webhook error: {e}", logging.WARNING)
        threading.Thread(target=send, daemon=True).start()

    async def _send_alert_with_logging(self, event_type, title, message, photo_path, details):
        """Log event locally first, then send Pushover (with notification filter)"""
        event = self.event_logger.log_event(event_type, details, photo_path)
        
        # Check notification config
        entity = details.get('entity') or details.get('vehicle_type') or 'person'
        entity_map = {'insan': 'person', 'kamyon': 'truck', 'araba': 'car', 'bisiklet': 'bicycle'}
        entity_key = entity_map.get(entity, entity)
        
        if not self.notifications_config.get(entity_key, True):
            log(f"🔕 Bildirim kapalı: {entity_key}")
            self.event_logger.log_push_result(event['event_id'], False, error="notification_disabled")
            return False
        
        try:
            success = await self.pushover.send_alert(title, message, photo_path, priority=1)
            self.event_logger.log_push_result(event['event_id'], success)
            return success
        except Exception as e:
            self.event_logger.log_push_result(event['event_id'], False, error=e)
            return False

    async def handle_normal_mode(self):
        """Normal mode with adaptive scanning"""
        SCAN_INTERVAL_IDLE = 1.0
        SCAN_INTERVAL_BOOST = 0.1
        
        last_scan = 0
        boost_until = 0
        schedule_logged = False
        
        while self.mode == SystemMode.NORMAL:
            now = time.time()
            
            # Schedule check
            if not self.is_scheduled_active():
                if not schedule_logged:
                    log("⏸️ Zamanlama dışı - bekleniyor")
                    schedule_logged = True
                await asyncio.sleep(10)
                continue
            elif schedule_logged:
                log("▶️ Zamanlama aktif - çalışıyor")
                schedule_logged = False
            
            if now < self.radar_latch_until:
                await asyncio.sleep(0.1)
                continue
            
            # Radar trigger
            if self.sensor.read_presence():
                boost_until = now + 10
                log("🚶 Radar tetiklendi → AI Boost")
                self.reset_counters()
                self.mode = SystemMode.HUMAN_MODE
                return
            
            # Adaptive scan interval
            in_boost = now < boost_until
            scan_interval = SCAN_INTERVAL_BOOST if in_boost else SCAN_INTERVAL_IDLE
            
            if (now - last_scan) >= scan_interval:
                last_scan = now
                
                photo, result = await self.take_and_analyze()
                if photo:
                    has_human = 'insan' in result['detected_classes']
                    has_truck = 'kamyon' in result['detected_classes']
                    has_car = 'araba' in result['detected_classes']
                    
                    # Update zone tracker
                    entity = 'insan' if has_human else ('kamyon' if has_truck else ('araba' if has_car else None))
                    zone_event = self.zone_tracker.update(has_human or has_truck or has_car, entity)
                    if zone_event:
                        self.event_logger.log_event(f"zone_{zone_event['type']}", zone_event)
                    
                    if has_human and 0 in self.enabled_classes:
                        log("👤 AI: İnsan tespit!")
                        self.reset_counters()
                        self.consecutive_human = 1
                        self.mode = SystemMode.HUMAN_MODE
                        try: os.remove(photo)
                        except: pass
                        return
                    
                    if has_truck and 7 in self.enabled_classes:
                        log("🚛 AI: Kamyon tespit!")
                        self.reset_counters()
                        self.consecutive_truck = 1
                        self._vehicle_type = 'kamyon'
                        self.mode = SystemMode.TRUCK_MODE
                        try: os.remove(photo)
                        except: pass
                        return
                    
                    if has_car and 2 in self.enabled_classes:
                        log("🚗 AI: Araba tespit!")
                        self.reset_counters()
                        self.consecutive_truck = 1
                        self._vehicle_type = 'araba'
                        self.mode = SystemMode.TRUCK_MODE
                        try: os.remove(photo)
                        except: pass
                        return
                    
                    try: os.remove(photo)
                    except: pass
            
            await asyncio.sleep(0.05)

    async def handle_human_mode(self):
        log("👤 İNSAN MODU")
        self.reset_counters()
        case_started = False
        alert_sent = False
        mode_start = time.time()
        case_start_time = 0
        
        self.radar_latch_until = time.time() + 5
        
        while self.mode == SystemMode.HUMAN_MODE:
            now = time.time()
            
            if now - mode_start > self.MODE_TIMEOUT:
                if case_started:
                    case = self.case_manager.close_case()
                    if case: self.ftp_manager.queue_case(case['dir'])
                self.mode = SystemMode.NORMAL
                return
            
            if case_started and (now - case_start_time) > self.AUTO_CASE_SPLIT_SECONDS:
                log("⏰ Auto case split (30 dk)")
                case = self.case_manager.close_case()
                if case: self.ftp_manager.queue_case(case['dir'])
                case_started = False
                alert_sent = False
            
            photo, result = await self.take_and_analyze()
            if not photo:
                continue
            
            has_human = 'insan' in result['detected_classes']
            has_truck = 'kamyon' in result['detected_classes']
            has_car = 'araba' in result['detected_classes']
            
            # Update zone tracker and log exit if detected
            entity = 'insan' if has_human else None
            zone_event = self.zone_tracker.update(has_human, entity)
            if zone_event and zone_event['type'] == 'exit':
                self.event_logger.log_event(f"zone_{zone_event['type']}", zone_event)
            
            if has_human:
                self.consecutive_human += 1
                self.consecutive_empty = 0
                log(f"👤 İnsan ({self.consecutive_human}/{self.CONFIRM_THRESHOLD}) conf={result['human_confidence']:.2f}")
                
                if self.consecutive_human >= self.CONFIRM_THRESHOLD:
                    if not case_started:
                        case_started = True
                        case_start_time = now
                        self.case_manager.start_case("insan")
                    
                    can_save = (now - self.last_human_photo_saved) >= self.HUMAN_PHOTO_INTERVAL
                    under_limit = len(self.case_manager.current_case['photos']) < self.MAX_CASE_PHOTOS
                    
                    if can_save and under_limit:
                        # NoIR correction only in day mode
                        if not self.camera.night_mode and self.noir_correction_enabled:
                            correct_noir_color(photo)
                        
                        saved_photo = self.case_manager.add_photo(photo)
                        self.last_human_photo_saved = now
                        
                        if not alert_sent and saved_photo:
                            alert_sent = True
                            details = {
                                'confidence': result['human_confidence'],
                                'is_night': result['is_night'],
                                'brightness': result['brightness'],
                                'zone_state': self.zone_tracker.get_state()['state']
                            }
                            asyncio.create_task(self._send_alert_with_logging(
                                "human_detected",
                                get_text("human_detected", self.config.get("LANGUAGE", "fi"), device_id=self.device_id),
                                get_text("human_detected_msg", self.config.get("LANGUAGE", "fi"), location=self.config.get('LOCATION', self.device_id), time=datetime.now().strftime('%H:%M:%S')),
                                saved_photo,
                                details
                            ))
                        continue
                    
            elif has_truck or has_car:
                self._vehicle_type = 'kamyon' if has_truck else 'araba'
                self.mode = SystemMode.TRUCK_MODE
                try: os.remove(photo)
                except: pass
                return
            else:
                self.consecutive_empty += 1
                if self.consecutive_empty > self.DETECTION_TOLERANCE:
                    self.consecutive_human = 0
            
            try: os.remove(photo)
            except: pass
            
            if self.consecutive_empty >= self.EXIT_THRESHOLD:
                log("📤 Kadrajdan çıkıldı")
                # Log zone exit
                zone_event = self.zone_tracker.update(False)
                if zone_event:
                    self.event_logger.log_event(f"zone_{zone_event['type']}", zone_event)
                
                if case_started:
                    case = self.case_manager.close_case()
                    if case: self.ftp_manager.queue_case(case['dir'])
                self.radar_latch_until = time.time() + 5
                self.mode = SystemMode.NORMAL
                return
            
            await asyncio.sleep(0.1)

    async def handle_truck_mode(self):
        vehicle_name = "Kamyon" if self._vehicle_type == 'kamyon' else "Araba"
        vehicle_emoji = "🚛" if self._vehicle_type == 'kamyon' else "🚗"
        log(f"{vehicle_emoji} {vehicle_name.upper()} MODU")
        
        self.sensor.pause()
        self.consecutive_empty = 0
        case_started = False
        alert_sent = False
        mode_start = time.time()
        case_start_time = 0
        
        while self.mode == SystemMode.TRUCK_MODE:
            now = time.time()
            
            if now - mode_start > self.MODE_TIMEOUT:
                if case_started:
                    case = self.case_manager.close_case()
                    if case: self.ftp_manager.queue_case(case['dir'])
                self.sensor.resume()
                self.mode = SystemMode.NORMAL
                return
            
            if case_started and (now - case_start_time) > self.AUTO_CASE_SPLIT_SECONDS:
                log("⏰ Auto case split (30 dk)")
                case = self.case_manager.close_case()
                if case: self.ftp_manager.queue_case(case['dir'])
                case_started = False
                alert_sent = False
            
            photo, result = await self.take_and_analyze()
            if not photo:
                continue
            
            has_truck = 'kamyon' in result['detected_classes']
            has_car = 'araba' in result['detected_classes']
            has_vehicle = has_truck or has_car
            has_human = 'insan' in result['detected_classes']
            
            # Update zone tracker and log exit if detected
            entity = 'kamyon' if has_truck else ('araba' if has_car else None)
            zone_event = self.zone_tracker.update(has_vehicle, entity)
            if zone_event and zone_event['type'] == 'exit':
                self.event_logger.log_event(f"zone_{zone_event['type']}", zone_event)
            
            if has_truck:
                self._vehicle_type = 'kamyon'
            elif has_car:
                self._vehicle_type = 'araba'
            
            if has_vehicle:
                self.consecutive_truck += 1
                self.consecutive_empty = 0
                v_emoji = "🚛" if has_truck else "🚗"
                v_name = "Kamyon" if has_truck else "Araba"
                log(f"{v_emoji} {v_name} ({self.consecutive_truck}/{self.CONFIRM_THRESHOLD}) conf={result['vehicle_confidence']:.2f}")
                
                if self.consecutive_truck >= self.CONFIRM_THRESHOLD:
                    if not case_started:
                        case_started = True
                        case_start_time = now
                        trigger = f"{self._vehicle_type}+insan" if has_human else self._vehicle_type
                        self.case_manager.start_case(trigger)
                    
                    can_save = (now - self.last_truck_photo_saved) >= self.TRUCK_PHOTO_INTERVAL
                    under_limit = len(self.case_manager.current_case['photos']) < self.MAX_CASE_PHOTOS
                    
                    if can_save and under_limit:
                        if not self.camera.night_mode and self.noir_correction_enabled:
                            correct_noir_color(photo)
                        
                        saved_photo = self.case_manager.add_photo(photo)
                        self.last_truck_photo_saved = now
                        
                        if not alert_sent and saved_photo:
                            alert_sent = True
                            
                            if self._vehicle_type == 'araba':
                                title = f"🚗 AUTO HAVAITTU - {self.device_id}"
                            else:
                                title = f"🚛 REKKA HAVAITTU - {self.device_id}"
                            
                            msg = get_text("human_detected_msg", self.config.get("LANGUAGE", "fi"), location=self.config.get('LOCATION', self.device_id), time=datetime.now().strftime('%H:%M:%S'))
                            if has_human:
                                msg += "\n⚠️ Henkilö/kuljettaja myös havaittu!"
                            
                            details = {
                                'vehicle_type': self._vehicle_type,
                                'confidence': result['vehicle_confidence'],
                                'human_present': has_human,
                                'is_night': result['is_night'],
                                'zone_state': self.zone_tracker.get_state()['state']
                            }
                            asyncio.create_task(self._send_alert_with_logging(
                                "vehicle_detected",
                                title,
                                msg,
                                saved_photo,
                                details
                            ))
                        continue
            else:
                self.consecutive_empty += 1
                if self.consecutive_empty > self.DETECTION_TOLERANCE:
                    self.consecutive_truck = 0
            
            try: os.remove(photo)
            except: pass
            
            if self.consecutive_empty >= self.EXIT_THRESHOLD:
                log(f"📤 {vehicle_name} çıktı")
                # Log zone exit
                zone_event = self.zone_tracker.update(False)
                if zone_event:
                    self.event_logger.log_event(f"zone_{zone_event['type']}", zone_event)
                
                if case_started:
                    case = self.case_manager.close_case()
                    if case: self.ftp_manager.queue_case(case['dir'])
                self.sensor.resume()
                self.mode = SystemMode.NORMAL
                return
            
            await asyncio.sleep(0.1)

    async def run(self):
        if not await self.initialize():
            return
        
        cal = self.system_config.get('SENSOR_CALIBRATION_SECONDS', 5)
        log(f"Kalibrasyon: {cal}s...")
        await asyncio.sleep(cal)
        log("✅ Sistem aktif")
        
        # Radar task (opsiyonel)
        if self.radar:
            asyncio.create_task(self._radar_loop())
        
        while True:
            try:
                if self.mode == SystemMode.NORMAL:
                    await self.handle_normal_mode()
                elif self.mode == SystemMode.HUMAN_MODE:
                    await self.handle_human_mode()
                elif self.mode == SystemMode.TRUCK_MODE:
                    await self.handle_truck_mode()
            except Exception as e:
                log(f"Hata: {e}\n{traceback.format_exc()}", logging.CRITICAL)
                self.mode = SystemMode.NORMAL
                self.sensor.resume()
                await asyncio.sleep(3)


    async def _radar_loop(self):
        """Radar mesafe okuma döngüsü - bağımsız çalışır"""
        log("📡 Radar loop başladı")
        while True:
            try:
                if self.radar:
                    presence, distance, zone, event = self.radar.read()
                    # Zone değişimi callback ile otomatik handle edilir
                await asyncio.sleep(0.15)
            except Exception as e:
                log(f"Radar loop error: {e}", logging.WARNING)
                await asyncio.sleep(1)

    async def cleanup(self):
        await self.camera.cleanup()
        await self.pushover.close()
        self.sensor.cleanup()

# ============ MAIN ============



async def run_self_test():
    """Comprehensive self-test for production readiness"""
    import sys
    
    # Load secrets from /etc/sentinel.env
    env_file = "/etc/sentinel.env"
    if os.path.exists(env_file):
        try:
            import subprocess
            result = subprocess.run(f"sudo cat {env_file}", shell=True, capture_output=True, text=True)
            for line in result.stdout.strip().split("\n"):
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
        except:
            pass
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "device_id": "unknown",
        "tests": {},
        "passed": 0,
        "failed": 0,
        "overall": "UNKNOWN"
    }
    
    def test(name, check_fn, critical=True):
        try:
            success, detail = check_fn()
            results["tests"][name] = {
                "status": "PASS" if success else "FAIL",
                "detail": detail,
                "critical": critical
            }
            if success:
                results["passed"] += 1
                print(f"  ✅ {name}: {detail}")
            else:
                results["failed"] += 1
                print(f"  ❌ {name}: {detail}")
            return success
        except Exception as e:
            results["tests"][name] = {
                "status": "ERROR",
                "detail": str(e),
                "critical": critical
            }
            results["failed"] += 1
            print(f"  ❌ {name}: ERROR - {e}")
            return False
    
    print("=" * 50)
    print("🔍 SENTINEL SELF-TEST")
    print("=" * 50)
    print()
    
    # 1. Config test
    def check_config():
        config_path = os.path.join(BASE_DIR, "config.json")
        if not os.path.exists(config_path):
            return False, "config.json not found"
        with open(config_path) as f:
            config = json.load(f)
        device_id = config.get("DEVICE_ID", "unknown")
        results["device_id"] = device_id
        return True, f"Loaded, device={device_id}"
    
    test("config", check_config)
    
    # 2. Environment secrets
    def check_secrets():
        required = ["PUSHOVER_APP_TOKEN", "PUSHOVER_GROUP_KEY"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            return False, f"Missing: {missing}"
        return True, "All secrets present"
    
    test("secrets", check_secrets)
    
    # 3. Model loading
    def check_model():
        model_path = os.path.join(BASE_DIR, "model", "detect.tflite")
        if not os.path.exists(model_path):
            return False, "Model file not found"
        size_mb = os.path.getsize(model_path) / 1024 / 1024
        return True, f"Found ({size_mb:.1f}MB)"
    
    test("model", check_model)
    
    # 4. Camera stream
    def check_camera():
        frame_path = "/dev/shm/sentinel/frame.jpg"
        if os.path.exists(frame_path):
            age = time.time() - os.path.getmtime(frame_path)
            if age < 5:
                return True, f"Frame fresh ({age:.1f}s old)"
            return False, f"Frame stale ({age:.1f}s old)"
        # Try to check if rpicam works
        result = os.system("rpicam-still --version > /dev/null 2>&1")
        if result == 0:
            return True, "rpicam available (no active stream)"
        return False, "rpicam not available"
    
    test("camera", check_camera)
    
    # 5. RAM disk writable
    def check_ramdisk():
        test_path = "/dev/shm/sentinel_test_write"
        try:
            os.makedirs("/dev/shm/sentinel", exist_ok=True)
            with open(test_path, 'w') as f:
                f.write("test")
            os.remove(test_path)
            return True, "/dev/shm writable"
        except Exception as e:
            return False, str(e)
    
    test("ramdisk", check_ramdisk)
    
    # 6. GPIO readable
    def check_gpio():
        gpio_path = "/sys/class/gpio/gpio17/value"
        if os.path.exists(gpio_path):
            return True, "GPIO17 accessible"
        # Try to check if GPIO is available at all
        if os.path.exists("/sys/class/gpio"):
            return True, "GPIO subsystem available"
        return False, "GPIO not available"
    
    test("gpio", check_gpio, critical=False)
    
    # 7. Internet connectivity
    def check_internet():
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=5)
            return True, "Connected"
        except Exception as e:
            return False, str(e)
    
    test("internet", check_internet)
    
    # 8. Pushover validation
    def check_pushover():
        token = os.environ.get("PUSHOVER_APP_TOKEN", "")
        key = os.environ.get("PUSHOVER_GROUP_KEY", "")
        if not token or not key:
            return False, "Credentials missing"
        if len(token) < 20 or len(key) < 20:
            return False, "Credentials too short"
        return True, "Credentials present (not validated)"
    
    test("pushover", check_pushover)
    
    # 9. FTP access (just check config, don't connect)
    def check_ftp():
        server = os.environ.get("FTP_SERVER", "")
        user = os.environ.get("FTP_USERNAME", "")
        if not server:
            return False, "FTP_SERVER not configured"
        if not user:
            return False, "FTP_USERNAME not configured"
        return True, f"Configured: {user}@{server}"
    
    test("ftp_config", check_ftp, critical=False)
    
    # 10. Disk space
    def check_disk():
        disk = psutil.disk_usage('/')
        free_mb = disk.free / 1024 / 1024
        if free_mb < 500:
            return False, f"Low: {free_mb:.0f}MB free"
        return True, f"{free_mb:.0f}MB free ({100-disk.percent:.1f}% available)"
    
    test("disk", check_disk)
    
    # Summary
    print()
    print("=" * 50)
    critical_failed = sum(1 for t in results["tests"].values() 
                         if t["status"] != "PASS" and t.get("critical", True))
    
    if critical_failed == 0:
        results["overall"] = "PASS"
        print(f"✅ OVERALL: PASS ({results['passed']}/{results['passed']+results['failed']} tests passed)")
    else:
        results["overall"] = "FAIL"
        print(f"❌ OVERALL: FAIL ({critical_failed} critical failures)")
    
    print("=" * 50)
    
    # Write JSON report
    report_path = os.path.join(BASE_DIR, "self_test_report.json")
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n📄 Report: {report_path}")
    
    # Exit code
    return 0 if results["overall"] == "PASS" else 2


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        setup_logging(LOG_FILE_PATH)
        exit_code = asyncio.run(run_self_test())
        sys.exit(exit_code)
    
    setup_logging(LOG_FILE_PATH)
    
    config_path = os.path.join(APP_DIR, 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
    except Exception as e:
        log(f"Config hatası: {e}", logging.CRITICAL)
        exit(1)
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           SENTINEL GÜVENLİK SİSTEMİ v3.12                    ║
║              Production Ready Edition                        ║
╠══════════════════════════════════════════════════════════════╣
║  Cihaz: {(CONFIG.get('DEVICE_ID') or socket.gethostname()):<50} ║
║  Features:                                                   ║
║    • Append-only event logging                               ║
║    • Zone-based entry/exit tracking                          ║
║    • FTP retry with exponential backoff                      ║
║    • Hardened watchdog (3-strike rule)                       ║
║    • 7-day log retention with auto-cleanup                   ║
║    • Adaptive threshold (day: 0.45, night: 0.30)            ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    sentinel = SentinelSystem(CONFIG)
    
    try:
        asyncio.run(sentinel.run())
    except KeyboardInterrupt:
        log("Durduruldu.")
    finally:
        try: asyncio.run(sentinel.cleanup())
        except: pass
        try: GPIO.cleanup()
        except: pass
