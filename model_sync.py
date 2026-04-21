#!/usr/bin/env python3
"""Model sync script - downloads model from backend if changed"""
import os
import json
import requests
import subprocess

BACKEND_URL = "http://141.144.242.141:8000"
MODELS_DIR = "/opt/sentinel/models"
CONFIG_FILE = "/opt/sentinel/config.json"

def get_current_model_id():
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            return config.get('MODEL_ID')
    except:
        return None

def get_device_model():
    try:
        with open('/etc/sentinel-device-id') as f:
            device_id = f.read().strip()
        resp = requests.get(f"{BACKEND_URL}/api/v1/devices/{device_id}", timeout=10)
        if resp.ok:
            return resp.json().get('model_id')
    except Exception as e:
        print(f"Error getting device model: {e}")
    return None

def download_model(model_id):
    os.makedirs(MODELS_DIR, exist_ok=True)
    filepath = os.path.join(MODELS_DIR, f"{model_id}.tflite")
    if os.path.exists(filepath):
        print(f"Model already exists: {filepath}")
        return filepath
    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/models/{model_id}/download", timeout=120, stream=True)
        if resp.ok:
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded model: {filepath} ({os.path.getsize(filepath)} bytes)")
            return filepath
        else:
            print(f"Download failed: {resp.status_code}")
    except Exception as e:
        print(f"Download error: {e}")
    return None

def update_config_model(model_id, model_path):
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        config['MODEL_ID'] = model_id
        config['MODEL_PATH'] = model_path
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"Config updated: {model_path}")
        return True
    except Exception as e:
        print(f"Config error: {e}")
    return False

if __name__ == "__main__":
    current = get_current_model_id()
    assigned = get_device_model()
    print(f"Current: {current}")
    print(f"Assigned: {assigned}")
    
    if assigned and assigned != current:
        print("Model changed! Downloading...")
        path = download_model(assigned)
        if path:
            update_config_model(assigned, path)
            print("Restarting sentinel service...")
            subprocess.run(['sudo', 'systemctl', 'restart', 'sentinel'], check=False)
            print("✅ Model updated and service restarted")
    else:
        print("Up to date")
