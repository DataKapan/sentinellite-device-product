#!/usr/bin/env python3
"""
RD-03 Radar Reader - Query Mode (JavaScript portuna benzer)
"""

import re
import time
import serial
import logging
import threading
from typing import Callable, Optional
from dataclasses import dataclass, field

@dataclass
class RadarConfig:
    port: str = '/dev/ttyAMA0'
    baud_rate: int = 115200
    min_range: float = 20.0
    max_range: float = 800.0
    motion_threshold: float = 30.0  # cm - hareket algılama eşiği
    motion_count: int = 3           # ardışık hareket sayısı
    no_motion_timeout: float = 5.0  # saniye - hareket yoksa exit
    max_speed_cm_s: float = 400.0   # cm/s - üzeri araba sayılır, tetiklenmez
    zones: dict = field(default_factory=dict)
    zone_confirm_count: int = 2

class RadarReader:
    CONFIG_CMD = bytes.fromhex('FDFCFBFA0800120000006400000004030201')
    
    def __init__(self, config: Optional[RadarConfig] = None):
        self.config = config or RadarConfig()
        self.ser = None
        self._lock = threading.Lock()
        
        # State
        self.initialized = False
        self.presence_active = False
        self.last_distance = 0.0
        self.last_valid_distance = 0.0
        self.last_activity_time = 0.0
        
        # Motion detection
        self.distance_history = []
        self.motion_count = 0
        
        # Zone
        self.current_zone = None
        self.pending_zone = None
        self.zone_confirm_counter = 0
        
        # Callbacks
        self.on_presence_change: Optional[Callable] = None
        self.on_zone_change: Optional[Callable] = None

    def initialize(self) -> bool:
        try:
            self.ser = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baud_rate,
                timeout=0.1
            )
            logging.info(f"📡 Serial opened: {self.config.port} @ {self.config.baud_rate}")
            
            # Config komutu gönder
            time.sleep(0.5)
            self.ser.write(self.CONFIG_CMD)
            logging.info("📡 Config komutu gönderildi")
            time.sleep(0.5)
            
            self.initialized = True
            self.last_activity_time = time.time()
            return True
        except Exception as e:
            logging.error(f"Radar init error: {e}")
            return False

    def _read_line(self) -> Optional[str]:
        """Sensörden satır oku"""
        if not self.ser or not self.ser.in_waiting:
            return None
        try:
            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
            return line if line else None
        except:
            return None

    def _parse_distance(self, line: str) -> Optional[float]:
        """'ON Range XXX' veya 'Range XXX' formatını parse et"""
        if 'Range' not in line:
            return None
        m = re.search(r'Range\s*:?\s*(\d+(?:\.\d+)?)', line)
        if m:
            try:
                return float(m.group(1))
            except:
                pass
        return None

    def _detect_motion(self, distance: float) -> bool:
        """Son mesafelere bakarak hareket var mı? Araba hızında ise False."""
        now = time.time()
        self.distance_history.append((now, distance))
        if len(self.distance_history) > 10:
            self.distance_history.pop(0)
        
        if len(self.distance_history) < 3:
            return False
        
        # Son 5 okumadaki min-max farkı
        recent = self.distance_history[-5:] if len(self.distance_history) >= 5 else self.distance_history
        distances = [d[1] for d in recent]
        spread = max(distances) - min(distances)
        
        # Hız kontrolü - ilk ve son okuma arası
        if len(recent) >= 2:
            t_start, d_start = recent[0]
            t_end, d_end = recent[-1]
            dt = t_end - t_start
            if dt > 0.05:
                speed = abs(d_end - d_start) / dt  # cm/s
                if speed > self.config.max_speed_cm_s:
                    # Araba hızı - tetikleme
                    return False
        
        return spread >= self.config.motion_threshold

    def _get_zone(self, distance: float) -> Optional[str]:
        if distance <= 0 or not self.config.zones:
            return None
        for name, cfg in self.config.zones.items():
            if cfg.get('min', 0) <= distance <= cfg.get('max', 999999):
                return name
        return None

    def _update_zone(self, distance: float):
        if not self.presence_active or distance <= 0:
            return
        
        new_zone = self._get_zone(distance)
        if new_zone is None:
            return
        
        if new_zone == self.current_zone:
            self.pending_zone = None
            self.zone_confirm_counter = 0
            return
        
        if new_zone == self.pending_zone:
            self.zone_confirm_counter += 1
        else:
            self.pending_zone = new_zone
            self.zone_confirm_counter = 1
        
        if self.zone_confirm_counter >= self.config.zone_confirm_count:
            old_zone = self.current_zone
            self.current_zone = new_zone
            self.pending_zone = None
            self.zone_confirm_counter = 0
            if self.on_zone_change:
                try:
                    self.on_zone_change(old_zone, new_zone, distance)
                except:
                    pass

    def read(self):
        """Ana okuma döngüsü - (presence, distance, zone, event) döner"""
        with self._lock:
            if not self.initialized:
                return False, 0.0, None, "NOT_INIT"
            
            now = time.time()
            event = ""
            
            # Satır oku
            line = self._read_line()
            distance = 0.0
            
            if line:
                dist = self._parse_distance(line)
                if dist is not None and self.config.min_range <= dist <= self.config.max_range:
                    distance = dist
                    self.last_distance = distance
                    self.last_valid_distance = distance
            
            # Hareket algılama
            old_presence = self.presence_active
            
            if distance > 0:
                has_motion = self._detect_motion(distance)
                
                if has_motion:
                    self.motion_count += 1
                    self.last_activity_time = now
                else:
                    self.motion_count = max(0, self.motion_count - 1)
                
                # Entry: yeterli hareket sayısı
                if not self.presence_active and self.motion_count >= self.config.motion_count:
                    self.presence_active = True
                    event = "ENTRY"
                    if self.on_presence_change:
                        try:
                            self.on_presence_change("ENTRY", distance)
                        except:
                            pass
            
            # Exit: timeout
            if self.presence_active:
                if now - self.last_activity_time > self.config.no_motion_timeout:
                    self.presence_active = False
                    self.motion_count = 0
                    self.distance_history.clear()
                    event = "EXIT"
                    # Zone reset
                    if self.current_zone and self.on_zone_change:
                        try:
                            self.on_zone_change(self.current_zone, None, 0.0)
                        except:
                            pass
                    self.current_zone = None
                    if self.on_presence_change:
                        try:
                            self.on_presence_change("EXIT", 0.0)
                        except:
                            pass
            
            # Zone update
            if self.presence_active and distance > 0:
                self._update_zone(distance)
            
            return (
                self.presence_active,
                self.last_valid_distance if self.presence_active else 0.0,
                self.current_zone,
                event
            )

    def get_status(self):
        with self._lock:
            return {
                'presence': self.presence_active,
                'distance_cm': self.last_valid_distance if self.presence_active else 0.0,
                'zone': self.current_zone,
                'motion_count': self.motion_count,
                'initialized': self.initialized,
            }

    def cleanup(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    cfg = RadarConfig(
        zones={
            'CRITICAL': {'min': 0, 'max': 100},
            'ALERT': {'min': 100, 'max': 300},
            'MONITOR': {'min': 300, 'max': 800},
        }
    )
    
    radar = RadarReader(cfg)
    
    def on_presence(event, d):
        if event == "ENTRY":
            print(f"\n🚨 ENTRY @ {d:.0f}cm\n")
        elif event == "EXIT":
            print(f"\n⚪ EXIT\n")
    
    def on_zone(old, new, d):
        print(f"\n🔔 ZONE: {old} → {new} ({d:.0f}cm)\n")
    
    radar.on_presence_change = on_presence
    radar.on_zone_change = on_zone
    
    if not radar.initialize():
        print("Init failed")
        exit(1)
    
    try:
        last_print = 0
        while True:
            p, d, z, e = radar.read()
            now = time.time()
            
            if now - last_print >= 0.5:
                last_print = now
                st = radar.get_status()
                icon = "🚨" if p else "⚪"
                zone_str = z if z else "---"
                print(f"{icon} D:{d:6.1f}cm | Z:{zone_str:8s} | motion={st['motion_count']}")
            
            time.sleep(0.05)
    
    except KeyboardInterrupt:
        print("\nDurduruldu")
    finally:
        radar.cleanup()
