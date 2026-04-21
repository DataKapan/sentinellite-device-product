import RPi.GPIO as GPIO
import serial
import time

GPIO.setmode(GPIO.BCM)
GPIO.setup(26, GPIO.IN)

print("--- Donanım Testi Başladı ---")
print("1. GPIO 26 (Varlık) Kontrol Ediliyor...")

try:
    # Pi Zero 2 W için doğru port
    ser = serial.Serial('/dev/serial0', 115200, timeout=1)
    print("2. UART (/dev/serial0) Portu Açıldı.")
    
    for i in range(10):
        presence = GPIO.input(26)
        status = "HAREKET VAR!" if presence else "Sakin..."
        print(f"[{i+1}] GPIO 26 Durumu: {status}")
        
        if ser.in_waiting > 0:
            raw_data = ser.read(ser.in_waiting)
            print(f"   -> Radardan Ham Veri Geldi: {len(raw_data)} byte")
        
        time.sleep(1)
except Exception as e:
    print(f"HATA: {e}")
finally:
    GPIO.cleanup()
    print("Test Tamamlandı.")
