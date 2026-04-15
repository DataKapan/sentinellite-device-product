#!/usr/bin/env python3
"""Check and execute pending commands from backend"""
import json
import os
import sys
import subprocess
import requests
import base64
from datetime import datetime
from PIL import Image
import numpy as np

def correct_noir_snapshot(path):
    """Apply NoIR color correction to snapshot"""
    try:
        # Load config
        with open('/opt/sentinel/config.json') as f:
            cfg = json.load(f)
        cam = cfg.get('CAMERA', {})
        if cam.get('TYPE') != 'noir' or not cam.get('NOIR_CORRECTION', True):
            return
        
        img = Image.open(path).convert("RGB")
        arr = np.asarray(img, dtype=np.float32) / 255.0
        
        # Simple white balance correction
        luma = arr.mean(axis=2)
        q1, q9 = np.quantile(luma, 0.10), np.quantile(luma, 0.90)
        mask = (luma > q1) & (luma < q9)
        
        if mask.sum() > 100:
            means = arr[mask].mean(axis=0)
            gains = means.mean() / (means + 1e-6)
        else:
            gains = np.array([1.0, 1.0, 1.0])
        
        gains *= np.array([0.75, 1.05, 1.20])
        arr *= gains.reshape(1, 1, 3)
        arr = np.clip(arr, 0, 1)
        
        Image.fromarray((arr * 255).astype(np.uint8)).save(path, quality=92)
        print("NoIR correction applied")
    except Exception as e:
        print(f"NoIR correction error: {e}")

BACKEND = "http://141.144.242.141:8000"
DEVICE_ID = open("/etc/sentinel-device-id").read().strip()

def get_pending_command():
    try:
        resp = requests.get(f"{BACKEND}/api/v1/devices/{DEVICE_ID}/config/check", timeout=10)
        data = resp.json()
        cmd = data.get('pending_command')
        return [cmd] if cmd else []
    except Exception as e:
        print(f"Error checking commands: {e}")
        return []

def take_snapshot():
    """Get current frame from sentinel stream with optional NoIR correction"""
    try:
        frame_path = "/dev/shm/sentinel/frame.jpg"
        if os.path.exists(frame_path):
            # Copy to temp for processing
            import shutil
            temp_path = "/tmp/snapshot_corrected.jpg"
            shutil.copy2(frame_path, temp_path)
            
            # Apply NoIR correction if enabled
            correct_noir_snapshot(temp_path)
            
            with open(temp_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        else:
            print("Frame not found - sentinel not running?")
            return None
    except Exception as e:
        print(f"Snapshot error: {e}")
        return None

def upload_snapshot(image_data):
    """Upload snapshot to backend"""
    try:
        resp = requests.post(
            f"{BACKEND}/api/v1/devices/{DEVICE_ID}/snapshot/upload",
            json={"image_data": image_data, "timestamp": datetime.now().isoformat()},
            timeout=30
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"Upload error: {e}")
        return False

def ack_command(cmd_id):
    """Acknowledge command completion"""
    try:
        requests.post(f"{BACKEND}/api/v1/devices/{DEVICE_ID}/command/{cmd_id}/ack", timeout=10)
    except:
        pass

def main():
    commands = get_pending_command()
    
    for cmd in commands:
        cmd_id = cmd.get('id')
        cmd_type = cmd.get('command')
        
        print(f"Executing command: {cmd_type}")
        
        if cmd_type == 'snapshot':
            image = take_snapshot()
            if image:
                if upload_snapshot(image):
                    print("Snapshot uploaded")
                    ack_command(cmd_id)
                else:
                    print("Snapshot upload failed")
            else:
                print("Snapshot capture failed")
                
        elif cmd_type == 'restart':
            ack_command(cmd_id)
            subprocess.run(["sudo", "systemctl", "restart", "sentinel"])
            
        elif cmd_type == 'log_upload':
            # TODO: implement log upload
            ack_command(cmd_id)

if __name__ == "__main__":
    main()
