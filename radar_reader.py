#!/usr/bin/env python3
"""RD-03 Radar Reader - Motion-based presence detection v4"""
import serial
import time
import logging
import threading
from collections import deque


class RadarConfig:
    PORT = '/dev/ttyAMA0'
    BAUD = 115200
    QUERY_HEX = 'FDFCFBFA0800120000006400000004030201'
    
    WINDOW = 20
    CALIBRATION_TIME = 5.0
    STABILIZATION_TIME = 10.0  # Kalibrasyon sonrası bekleme
    
    ENTRY_DEVIATION = 50
    MOTION_THRESHOLD = 15
    ENTRY_COUNT = 4
    
    EXIT_BASELINE_TOLERANCE = 30
    EXIT_BASELINE_COUNT = 5


class RadarReader:
    def __init__(self, config=None):
        self.config = config or {}
        self.port = self.config.get('PORT', RadarConfig.PORT)
        self.baud = self.config.get('BAUD', RadarConfig.BAUD)
        self.zones = self.config.get('ZONES', {})
        
        self.ser = None
        self.readings = deque(maxlen=RadarConfig.WINDOW)
        self.baseline = None
        self.calibration_start = None
        self.stabilization_end = None  # Stabilizasyon bitiş zamanı
        self.presence_active = False
        self.entry_counter = 0
        self.exit_counter = 0
        self.last_dist = None
        self.last_distance = None
        self.current_zone = None
        self.initialized = False
        self._lock = threading.Lock()
        
        self.on_zone_change = None
        self.on_presence_change = None

    def initialize(self):
        try:
            self.ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=1)
            self.calibration_start = time.time()
            self.initialized = True
            logging.info(f"📡 Radar: {self.port} @ {self.baud}")
            logging.info("📡 Kalibrasyon (5s uzak dur)...")
            return True
        except Exception as e:
            logging.error(f"Radar init error: {e}")
            return False

    def _read_raw(self):
        try:
            self.ser.write(bytes.fromhex(RadarConfig.QUERY_HEX))
            time.sleep(0.12)
            raw = b""
            deadline = time.time() + 0.2
            while time.time() < deadline:
                if self.ser.in_waiting:
                    raw += self.ser.read(self.ser.in_waiting)
                else:
                    time.sleep(0.01)
            
            text = raw.decode('utf-8', errors='ignore')
            if "Range" in text:
                return float(text.split("Range")[-1].strip().split()[0])
        except serial.SerialException:
            try:
                self.ser.close()
                time.sleep(0.5)
                self.ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=1)
            except:
                pass
        except:
            pass
        return None

    def _get_zone(self, distance):
        if not distance or not self.zones:
            return None
        for name, cfg in self.zones.items():
            if cfg.get('min', 0) <= distance <= cfg.get('max', 9999):
                return name
        return None

    def _is_stabilizing(self):
        """Stabilizasyon süresinde mi?"""
        if self.stabilization_end is None:
            return True
        return time.time() < self.stabilization_end

    def read(self):
        with self._lock:
            dist = self._read_raw()
            
            if dist and 20 < dist < 1500:
                self.readings.append(dist)
                self.last_distance = dist
            
            # Kalibrasyon
            if self.baseline is None:
                elapsed = time.time() - self.calibration_start
                if elapsed < RadarConfig.CALIBRATION_TIME:
                    return False, self.last_distance, None, f"CAL {5-int(elapsed)}s"
                
                if len(self.readings) >= 10:
                    self.baseline = sum(self.readings) / len(self.readings)
                    self.stabilization_end = time.time() + RadarConfig.STABILIZATION_TIME
                    logging.info(f"📡 Baseline: {self.baseline:.0f}cm (stabil: 10s)")
                else:
                    self.calibration_start = time.time()
                    return False, self.last_distance, None, "RECAL"
            
            # Stabilizasyon - callback yok
            if self._is_stabilizing():
                remain = int(self.stabilization_end - time.time())
                return False, self.last_distance, None, f"STAB {remain}s"
            
            if not dist:
                return self.presence_active, self.last_distance, self.current_zone, ""
            
            avg = sum(self.readings) / len(self.readings)
            deviation = abs(avg - self.baseline)
            motion = abs(dist - self.last_dist) if self.last_dist else 0
            is_motion = motion > RadarConfig.MOTION_THRESHOLD
            is_deviated = deviation > RadarConfig.ENTRY_DEVIATION
            near_baseline = deviation < RadarConfig.EXIT_BASELINE_TOLERANCE
            self.last_dist = dist
            
            event = ""
            old_presence = self.presence_active
            
            if not self.presence_active:
                if is_deviated and is_motion:
                    self.entry_counter += 1
                    if self.entry_counter >= RadarConfig.ENTRY_COUNT:
                        self.presence_active = True
                        self.exit_counter = 0
                        event = "ENTRY"
                elif not is_deviated:
                    self.entry_counter = 0
            else:
                if near_baseline:
                    self.exit_counter += 1
                    if self.exit_counter >= RadarConfig.EXIT_BASELINE_COUNT:
                        self.presence_active = False
                        self.entry_counter = 0
                        self.exit_counter = 0
                        self.baseline = avg
                        event = "EXIT"
                else:
                    self.exit_counter = 0
            
            # Callbacks - SADECE stabilizasyon bittikten sonra
            if old_presence != self.presence_active and self.on_presence_change:
                self.on_presence_change(self.presence_active, self.last_distance)
            
            new_zone = self._get_zone(self.last_distance) if self.presence_active else None
            if self.presence_active and new_zone and new_zone != self.current_zone:
                old_zone = self.current_zone
                self.current_zone = new_zone
                if self.on_zone_change:
                    self.on_zone_change(old_zone, new_zone, self.last_distance)
            elif not self.presence_active:
                self.current_zone = None
            
            return self.presence_active, self.last_distance, self.current_zone, event

    def get_status(self):
        with self._lock:
            return {
                'presence': self.presence_active,
                'distance_cm': self.last_distance,
                'zone': self.current_zone,
                'baseline': self.baseline,
                'initialized': self.initialized
            }

    def cleanup(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    zones = {
        'CRITICAL': {'min': 0, 'max': 200},
        'ALERT': {'min': 200, 'max': 500},
        'MONITOR': {'min': 500, 'max': 1000}
    }
    
    radar = RadarReader({'ZONES': zones})
    radar.on_zone_change = lambda o, n, d: print(f"\n🔔 ZONE: {o} → {n} ({d}cm)\n")
    radar.on_presence_change = lambda p, d: print(f"\n{'🚨 ENTRY' if p else '⚪ EXIT'} @ {d}cm\n")
    
    if radar.initialize():
        try:
            while True:
                p, d, z, e = radar.read()
                st = radar.get_status()
                base = st.get('baseline') or 0
                dev = abs((d or 0) - base)
                s = "🚨" if p else "⚪"
                print(f"{s} D:{d or 0:.0f} | base:{base:.0f} | dev:{dev:.0f} | Z:{z or '---'} {e}")
                time.sleep(0.15)
        except KeyboardInterrupt:
            print("\nDurduruldu")
        finally:
            radar.cleanup()
