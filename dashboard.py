import os
import json
import psutil
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from utils.db import (
    get_accounts, add_account, delete_account, set_account_active,
    get_recent_trades, get_recent_signals, get_recent_logs,
    get_settings, save_settings, add_log
)

app = FastAPI(title="Antigravity MT5 Copier Dashboard")

# Enable CORS for easy local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store in-memory Telethon login clients temporarily
# Schema: { phone: {"client": TelegramClient, "hash": str} }
active_logins = {}

class AccountCreate(BaseModel):
    login: int
    password: str
    server: str
    terminal_path: str
    risk_pct: Optional[float] = 1.0

class SettingsUpdate(BaseModel):
    api_id: str
    api_hash: str
    phone: str
    monitored_channels: List[str]

class TelegramCodeSend(BaseModel):
    phone: str

class TelegramLogin(BaseModel):
    phone: str
    code: str
    password: Optional[str] = None # For 2FA if needed

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """
    Serves the main HTML dashboard file directly.
    """
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "templates", "index.html"))
    if not os.path.exists(html_path):
        return HTMLResponse("<h1>Dashboard templates/index.html not found!</h1>", status_code=404)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/stats")
async def get_stats():
    """
    Returns global trade and system performance statistics.
    """
    try:
        accounts = get_accounts()
        total_balance = sum(a["balance"] for a in accounts)
        total_equity = sum(a["equity"] for a in accounts)
        
        # Get count of active trades
        recent_trades = get_recent_trades(100)
        open_trades_count = sum(1 for t in recent_trades if t["status"] == "open")
        
        # Get VPS Resource Info
        cpu_percent = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        ram_percent = ram.percent
        
        return {
            "total_balance": total_balance,
            "total_equity": total_equity,
            "open_trades": open_trades_count,
            "vps_cpu": cpu_percent,
            "vps_ram": ram_percent,
            "accounts_count": len(accounts)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def api_get_accounts():
    return get_accounts()

@app.post("/api/accounts")
async def api_add_account(acc: AccountCreate):
    success = add_account(
        login=acc.login,
        password=acc.password,
        server=acc.server,
        terminal_path=acc.terminal_path,
        risk_pct=acc.risk_pct
    )
    if not success:
        raise HTTPException(status_code=400, detail="Account login already exists")
    return {"status": "success", "message": f"Account {acc.login} added successfully."}

@app.post("/api/accounts/{account_id}/toggle")
async def api_toggle_account(account_id: int, request: Request):
    data = await request.json()
    is_active = data.get("is_active", True)
    set_account_active(account_id, is_active)
    status_str = "activated" if is_active else "deactivated"
    add_log("INFO", "dashboard", f"Account ID {account_id} has been {status_str}")
    return {"status": "success", "message": f"Account {status_str}."}

@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int):
    delete_account(account_id)
    return {"status": "success", "message": "Account deleted successfully."}

@app.get("/api/trades")
async def api_get_trades():
    return get_recent_trades(50)

@app.get("/api/signals")
async def api_get_signals():
    return get_recent_signals(20)

@app.get("/api/logs")
async def api_get_logs():
    return get_recent_logs(100)

@app.get("/api/settings")
async def api_get_settings():
    settings = get_settings()
    # Monitored channels are stored as JSON string
    try:
        monitored_channels = json.loads(settings.get("monitored_channels", "[]"))
    except Exception:
        monitored_channels = []
    return {
        "api_id": settings.get("api_id", ""),
        "api_hash": settings.get("api_hash", ""),
        "phone": settings.get("phone", ""),
        "monitored_channels": monitored_channels,
        "telegram_status": settings.get("telegram_status", "disconnected")
    }

@app.post("/api/settings")
async def api_save_settings(settings: SettingsUpdate):
    save_settings({
        "api_id": settings.api_id.strip(),
        "api_hash": settings.api_hash.strip(),
        "phone": settings.phone.strip(),
        "monitored_channels": json.dumps(settings.monitored_channels)
    })
    return {"status": "success", "message": "Settings saved successfully."}

@app.post("/api/telegram/send_code")
async def api_telegram_send_code(payload: TelegramCodeSend):
    phone = payload.phone.strip()
    settings = get_settings()
    api_id_str = settings.get("api_id", "")
    api_hash = settings.get("api_hash", "")
    
    if not api_id_str or not api_hash:
        raise HTTPException(status_code=400, detail="Telegram API credentials are not configured in settings.")
        
    try:
        api_id = int(api_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="API ID must be an integer.")
        
    # Build session file path
    session_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "telegram"))
    
    # Instantiate client
    client = TelegramClient(session_path, api_id, api_hash)
    
    try:
        await client.connect()
        # Request code
        result = await client.send_code_request(phone)
        
        # Save client and hash in-memory
        active_logins[phone] = {
            "client": client,
            "hash": result.phone_code_hash
        }
        
        add_log("INFO", "dashboard", f"Sent verification code to {phone}")
        return {"status": "success", "message": "Code sent successfully."}
    except Exception as e:
        add_log("ERROR", "dashboard", f"Failed to send Telegram code to {phone}: {e}")
        # Make sure to disconnect if active
        if client:
            await client.disconnect()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/login")
async def api_telegram_login(payload: TelegramLogin):
    phone = payload.phone.strip()
    code = payload.code.strip()
    password = payload.password.strip() if payload.password else None
    
    if phone not in active_logins:
        raise HTTPException(status_code=400, detail="Verification session expired or not found. Please resend code.")
        
    login_data = active_logins[phone]
    client = login_data["client"]
    phone_code_hash = login_data["hash"]
    
    try:
        if password:
            # Complete login with 2FA password
            await client.sign_in(phone=phone, code=code, password=password, phone_code_hash=phone_code_hash)
        else:
            try:
                # Complete standard login
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                # 2FA password is required
                return JSONResponse(status_code=202, content={
                    "status": "2fa_required",
                    "message": "Two-factor authentication (2FA) password is required to login."
                })
                
        # Successful login
        save_settings({"telegram_status": "connected", "phone": phone})
        add_log("INFO", "dashboard", f"Successfully logged into Telegram account {phone}")
        
        # Clean up temporary storage and disconnect client
        # Note: Disconnect will let the separate listener process claim the session lock
        await client.disconnect()
        del active_logins[phone]
        
        return {"status": "success", "message": "Logged into Telegram successfully."}
    except Exception as e:
        add_log("ERROR", "dashboard", f"Failed to complete Telegram login for {phone}: {e}")
        # Disconnect client
        await client.disconnect()
        if phone in active_logins:
            del active_logins[phone]
        raise HTTPException(status_code=500, detail=str(e))
