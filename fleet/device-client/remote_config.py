"""
Sentinel Remote Config Client
Cihazda çalışır, backend'den config çeker
"""

import asyncio
import httpx
import json
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

class RemoteConfigClient:
    def __init__(self, 
                 device_id: str,
                 backend_url: str = "https://api.sentinel.datatrap.fi",
                 config_path: str = "/home/sentinellite/sentinel/config.json",
                 poll_interval: int = 60):
        
        self.device_id = device_id
        self.backend_url = backend_url.rstrip('/')
        self.config_path = config_path
        self.poll_interval = poll_interval
        self.current_version = 0
        self.logger = logging.getLogger("RemoteConfig")
        
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"X-Device-Key": device_id}
        )
        self.on_config_update = None
        self.on_credentials_update = None
    
    async def register(self, firmware_version: str = None) -> bool:
        try:
            resp = await self.client.post(
                f"{self.backend_url}/api/v1/devices/register",
                json={"device_id": self.device_id, "firmware_version": firmware_version or "3.12-prod"}
            )
            return resp.status_code == 200
        except Exception as e:
            self.logger.error(f"Registration failed: {e}")
            return False
    
    async def fetch_config(self) -> Optional[Dict[str, Any]]:
        try:
            resp = await self.client.get(f"{self.backend_url}/api/v1/devices/{self.device_id}/config")
            return resp.json() if resp.status_code == 200 else None
        except Exception as e:
            self.logger.error(f"Config fetch failed: {e}")
            return None
    
    async def ack_config(self, version: int) -> bool:
        try:
            resp = await self.client.post(
                f"{self.backend_url}/api/v1/devices/{self.device_id}/config/ack",
                params={"version": version}
            )
            return resp.status_code == 200
        except:
            return False
    
    async def send_telemetry(self, telemetry: Dict[str, Any]) -> bool:
        try:
            resp = await self.client.post(
                f"{self.backend_url}/api/v1/devices/{self.device_id}/telemetry",
                json=telemetry
            )
            return resp.status_code == 200
        except:
            return False
    
    async def send_events(self, events: list) -> bool:
        try:
            resp = await self.client.post(
                f"{self.backend_url}/api/v1/devices/{self.device_id}/events",
                json=events
            )
            return resp.status_code == 200
        except:
            return False
    
    def apply_credentials(self, credentials: Dict[str, Any]) -> bool:
        try:
            if 'ftp' in credentials and credentials['ftp'].get('enabled'):
                ftp = credentials['ftp']
                if ftp.get('server'): os.environ['FTP_SERVER'] = ftp['server']
                if ftp.get('username'): os.environ['FTP_USERNAME'] = ftp['username']
                if ftp.get('password') and ftp['password'] != '******':
                    os.environ['FTP_PASSWORD'] = ftp['password']
            
            if 'pushover' in credentials and credentials['pushover'].get('enabled'):
                push = credentials['pushover']
                if push.get('app_token') and push['app_token'] != '******':
                    os.environ['PUSHOVER_APP_TOKEN'] = push['app_token']
                if push.get('group_key') and push['group_key'] != '******':
                    os.environ['PUSHOVER_GROUP_KEY'] = push['group_key']
            
            if self.on_credentials_update:
                self.on_credentials_update(credentials)
            return True
        except Exception as e:
            self.logger.error(f"Credentials apply failed: {e}")
            return False
    
    async def poll_loop(self):
        self.logger.info(f"Remote config polling started")
        while True:
            try:
                data = await self.fetch_config()
                if data and data.get('config_version', 0) > self.current_version:
                    self.logger.info(f"New config: v{data['config_version']}")
                    if 'credentials' in data:
                        self.apply_credentials(data['credentials'])
                    await self.ack_config(data['config_version'])
                    self.current_version = data['config_version']
            except Exception as e:
                self.logger.error(f"Poll error: {e}")
            await asyncio.sleep(self.poll_interval)
    
    async def close(self):
        await self.client.aclose()
