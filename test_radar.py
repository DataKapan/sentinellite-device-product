#!/usr/bin/env python3
"""Ai-Thinker RD-03 Radar Test - Multi Target Mode"""
import serial
import time
import math
import struct

SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 256000

# Commands
MULTI_TARGET_CMD = bytes([0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x90, 0x00, 0x04, 0x03, 0x02, 0x01])

def parse_target(buf, offset=0):
    """Parse 8 bytes target data"""
    if len(buf) < offset + 8:
        return None
    
    raw_x = buf[offset] | (buf[offset+1] << 8)
    raw_y = buf[offset+2] | (buf[offset+3] << 8)
    raw_speed = buf[offset+4] | (buf[offset+5] << 8)
    raw_pixel = buf[offset+6] | (buf[offset+7] << 8)
    
    # Check if detected
    if raw_x == 0 and raw_y == 0 and raw_speed == 0 and raw_pixel == 0:
        return None
    
    # Parse signed values
    x = ((1 if raw_x & 0x8000 else -1) * (raw_x & 0x7FFF))
    y = ((1 if raw_y & 0x8000 else -1) * (raw_y & 0x7FFF))
    speed = ((1 if raw_speed & 0x8000 else -1) * (raw_speed & 0x7FFF))
    
    distance = math.sqrt(x*x + y*y)  # mm
    angle = math.degrees(math.atan2(y, x) - (math.pi / 2)) * -1
    
    return {
        'x': x,
        'y': y,
        'distance_mm': round(distance),
        'distance_m': round(distance / 1000, 2),
        'speed': speed,
        'angle': round(angle, 1)
    }

def main():
    print(f"RD-03 Radar Test ({SERIAL_PORT} @ {BAUD_RATE})")
    
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print("Serial OK")
    
    # Send multi-target mode command
    ser.write(MULTI_TARGET_CMD)
    print("Multi-target mode gönderildi")
    time.sleep(0.5)
    
    # State machine
    state = 'WAIT_AA'
    buffer = bytearray()
    
    try:
        while True:
            if ser.in_waiting > 0:
                byte = ser.read(1)[0]
                
                if state == 'WAIT_AA':
                    if byte == 0xAA:
                        state = 'WAIT_FF'
                elif state == 'WAIT_FF':
                    if byte == 0xFF:
                        state = 'WAIT_03'
                    else:
                        state = 'WAIT_AA'
                elif state == 'WAIT_03':
                    if byte == 0x03:
                        state = 'WAIT_00'
                    else:
                        state = 'WAIT_AA'
                elif state == 'WAIT_00':
                    if byte == 0x00:
                        buffer = bytearray()
                        state = 'RECEIVE'
                    else:
                        state = 'WAIT_AA'
                elif state == 'RECEIVE':
                    buffer.append(byte)
                    if len(buffer) >= 26:  # 24 data + 2 tail
                        if buffer[24] == 0x55 and buffer[25] == 0xCC:
                            # Parse 3 targets
                            for i in range(3):
                                target = parse_target(buffer, i * 8)
                                if target:
                                    print(f"T{i}: {target['distance_m']}m, açı:{target['angle']}°, hız:{target['speed']}cm/s")
                        state = 'WAIT_AA'
                        buffer = bytearray()
            else:
                time.sleep(0.01)
                
    except KeyboardInterrupt:
        print("\nDurduruldu")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
