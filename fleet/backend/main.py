"""Sentinel Fleet Management Backend - FastAPI"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from cryptography.fernet import Fernet
import asyncpg
import os
import json
import hashlib
import secrets

app = FastAPI(title="Sentinel Fleet API", version="1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sentinel:sentinel@localhost/sentinel")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
fernet = Fernet(ENCRYPTION_KEY.encode())
db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    await init_db()

async def init_db():
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                device_id VARCHAR(100) UNIQUE NOT NULL,
                tenant_id UUID,
                status VARCHAR(50) DEFAULT 'pending',
                config_version INTEGER DEFAULT 1,
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS device_configs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                device_id UUID REFERENCES devices(id),
                version INTEGER NOT NULL,
                config JSONB,
                credentials_encrypted BYTEA,
                created_at TIMESTAMP DEFAULT NOW()
            );
        ''')

class DeviceReg(BaseModel):
    device_id: str
    firmware_version: Optional[str] = None

@app.post("/api/v1/devices/register")
async def register(reg: DeviceReg):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM devices WHERE device_id=$1", reg.device_id)
        if existing:
            await conn.execute("UPDATE devices SET last_seen=NOW() WHERE device_id=$1", reg.device_id)
            return {"status": "exists"}
        await conn.execute("INSERT INTO devices(device_id,last_seen) VALUES($1,NOW())", reg.device_id)
        return {"status": "registered"}

@app.get("/api/v1/devices/{device_id}/config")
async def get_config(device_id: str):
    async with db_pool.acquire() as conn:
        dev = await conn.fetchrow('''
            SELECT d.config_version, dc.config, dc.credentials_encrypted
            FROM devices d LEFT JOIN device_configs dc ON dc.device_id=d.id AND dc.version=d.config_version
            WHERE d.device_id=$1
        ''', device_id)
        if not dev: raise HTTPException(404)
        await conn.execute("UPDATE devices SET last_seen=NOW() WHERE device_id=$1", device_id)
        creds = json.loads(fernet.decrypt(dev['credentials_encrypted']).decode()) if dev['credentials_encrypted'] else {}
        return {"config_version": dev['config_version'], "config": dev['config'] or {}, "credentials": creds}

@app.post("/api/v1/devices/{device_id}/config/ack")
async def ack_config(device_id: str, version: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE devices SET last_config_ack=$2 WHERE device_id=$1", device_id, version)
    return {"status": "ok"}

@app.post("/api/v1/devices/{device_id}/telemetry")
async def telemetry(device_id: str, data: dict):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE devices SET last_seen=NOW() WHERE device_id=$1", device_id)
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
