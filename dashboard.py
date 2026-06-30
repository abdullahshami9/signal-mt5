import os
import sys
import json
import psutil
import asyncio
from fastapi import FastAPI, HTTPException, Request, Cookie, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from utils.db import (
    get_accounts, add_account, delete_account, set_account_active,
    get_recent_trades, get_recent_signals, get_recent_logs,
    get_settings, save_settings, add_log, add_signal, get_db_connection, get_account,
    verify_session, authenticate_user, create_session, create_user, delete_session,
    sync_data_to_live, sync_all_local_users_to_live
)
from utils.terminal_provisioner import terminate_executor_and_terminal

app = FastAPI(title="Quanthropic.dev MT5 Copier Dashboard")

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), relative_path))

# Enable CORS for easy local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Idle tracking for background synchronization
import time
import threading

last_request_time = time.time()

@app.middleware("http")
async def update_last_request_time(request: Request, call_next):
    global last_request_time
    last_request_time = time.time()
    response = await call_next(request)
    return response

def background_sync_loop():
    global last_request_time
    # Initial sleep to allow the dashboard and executors to boot up fully
    time.sleep(10)
    while True:
        try:
            now = time.time()
            # If the application has been idle for more than 15 seconds, trigger synchronization
            if now - last_request_time > 15:
                sync_all_local_users_to_live()
        except Exception as e:
            print(f"Background sync error: {e}")
        time.sleep(30)

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=background_sync_loop, daemon=True).start()

# Store in-memory Telethon login clients temporarily
# Schema: { phone: {"client": TelegramClient, "hash": str} }
active_logins = {}

# Flag to signal that the UI has successfully fetched data
ui_fetched_accounts = False

class AccountCreate(BaseModel):
    login: int
    password: str
    server: str
    terminal_path: Optional[str] = None
    risk_pct: Optional[float] = 1.0
    name: Optional[str] = None
    payment_date: Optional[str] = None

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

class SignalCreate(BaseModel):
    action: str
    symbol: str
    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None

class LoginPayload(BaseModel):
    username: str
    password: str

class RegisterPayload(BaseModel):
    username: str
    password: str

async def get_current_user(session_token: Optional[str] = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = verify_session(session_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, session_token: Optional[str] = Cookie(None)):
    """
    Serves the main HTML dashboard file directly if logged in, otherwise redirects to /login.
    """
    if not session_token or not verify_session(session_token):
        return RedirectResponse(url="/login", status_code=303)
        
    html_path = get_resource_path(os.path.join("templates", "index.html"))
    if not os.path.exists(html_path):
        return HTMLResponse("<h1>Dashboard templates/index.html not found!</h1>", status_code=404)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request, session_token: Optional[str] = Cookie(None)):
    """
    Serves the login page. If already logged in, redirects to the dashboard.
    """
    if session_token and verify_session(session_token):
        return RedirectResponse(url="/", status_code=303)
        
    html_path = get_resource_path(os.path.join("templates", "login.html"))
    if not os.path.exists(html_path):
        return HTMLResponse("<h1>Login templates/login.html not found!</h1>", status_code=404)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/login")
async def api_login(payload: LoginPayload):
    username = payload.username.strip()
    password = payload.password
    
    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid username or password")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail="Your account is blocked. Please contact the administrator.")
        
    session_token = create_session(user["id"])
    
    response = JSONResponse(content={"status": "success", "message": "Logged in successfully"})
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=30 * 24 * 60 * 60, # 30 days
        samesite="lax"
    )
    return response

@app.post("/api/sync")
async def api_trigger_sync(current_user: int = Depends(get_current_user)):
    success, message = sync_data_to_live(current_user, force=True)
    if not success:
        raise HTTPException(status_code=500, detail=message)
    return {"status": "success", "message": message}

@app.post("/api/register")
async def api_register(payload: RegisterPayload):
    username = payload.username.strip()
    password = payload.password
    
    if len(username) < 3 or len(password) < 5:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters, password at least 5 characters")
        
    success = create_user(username, password)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
        
    return {"status": "success", "message": "User registered successfully. Please login."}

@app.post("/api/logout")
async def api_logout(session_token: Optional[str] = Cookie(None)):
    if session_token:
        user_id = verify_session(session_token)
        if user_id:
            # 1. Fetch all accounts of this user
            accounts = get_accounts(user_id=user_id)
            for acc in accounts:
                acc_id = acc["id"]
                login = acc["login"]
                terminal_path = acc.get("terminal_path")
                
                # 2. Deactivate the account in the DB so the orchestrator won't restart it
                set_account_active(acc_id, False)
                
                # 3. Force stop executor and close MT5 terminal process
                if terminal_path:
                    try:
                        terminate_executor_and_terminal(login, acc_id, terminal_path)
                    except Exception as e:
                        print(f"Error stopping terminal on logout: {e}")
            
            # 4. Delete session token from DB
            delete_session(session_token)
            
    response = JSONResponse(content={"status": "success", "message": "Logged out successfully"})
    response.delete_cookie(key="session_token")
    return response

@app.get("/signal_checker")
async def signal_checker(symbol: str = "XAUUSD", action: str = "BUY", current_user: int = Depends(get_current_user)):
    """
    Test endpoint to automatically inject a signal for 0.01 lot trade execution.
    """
    try:
        action = action.upper().strip()
        if action not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="Action must be BUY or SELL")
            
        symbol = symbol.upper().strip()
        
        # Add a dummy signal with telegram_msg_id=9999 to identify as manual test
        # Using a raw_text prefix of TEST_SIGNAL so the executor knows to use 0.01 lots and bypass SL.
        msg_id = 9999
        channel_id = 0
        raw_text = f"TEST_SIGNAL: {action} {symbol}"
        
        signal_id = add_signal(
            telegram_msg_id=msg_id,
            channel_id=channel_id,
            raw_text=raw_text,
            action=action,
            symbol=symbol,
            sl=None,
            tp1=None,
            tp2=None,
            tp3=None,
            user_id=current_user
        )
        
        add_log("INFO", f"dashboard_user_{current_user}", f"Injected manual test signal {signal_id} ({action} {symbol}) via /signal_checker", user_id=current_user)
        return {
            "status": "success",
            "message": f"Test signal injected successfully.",
            "signal_id": signal_id,
            "action": action,
            "symbol": symbol,
            "lot_size": 0.01
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_stats(current_user: int = Depends(get_current_user)):
    """
    Returns global trade and system performance statistics.
    """
    global ui_fetched_accounts
    ui_fetched_accounts = True
    try:
        accounts = get_accounts(user_id=current_user)
        total_balance = sum(a["balance"] for a in accounts)
        total_equity = sum(a["equity"] for a in accounts)
        
        # Get count of active trades
        recent_trades = get_recent_trades(100, user_id=current_user)
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

POPULAR_MT5_SERVERS = [
    "DooTechnology-Live",
    "DooTechnology-Live-2",
    "DooTechnology-Live-3",
    "DooTechnology-Demo",
    "XMGlobal-MT5",
    "XMGlobal-MT5 2",
    "XMGlobal-MT5 3",
    "XMGlobal-MT5 4",
    "XMGlobal-MT5 5",
    "XMGlobal-MT5 6",
    "XMGlobal-Demo",
    "Exness-MT5Real",
    "Exness-MT5Real2",
    "Exness-MT5Real3",
    "Exness-MT5Real4",
    "Exness-MT5Real5",
    "Exness-MT5Real6",
    "Exness-MT5Real7",
    "Exness-MT5Real8",
    "Exness-MT5Real9",
    "Exness-MT5Real10",
    "Exness-MT5Trial",
    "Exness-MT5Trial2",
    "ICMarketsSC-Demo",
    "ICMarketsSC-Live01",
    "ICMarketsSC-Live02",
    "ICMarketsSC-Live03",
    "ICMarketsSC-Live04",
    "ICMarketsSC-Live05",
    "ICMarketsSC-Live06",
    "ICMarketsSC-Live07",
    "ICMarketsSC-Live08",
    "ICMarketsSC-Live09",
    "ICMarketsSC-Live10",
    "ICMarkets-Demo",
    "ICMarkets-Live01",
    "Pepperstone-MT5-Demo",
    "Pepperstone-MT5-Live",
    "RoboForex-Demo",
    "RoboForex-Pro",
    "RoboForex-ProCent",
    "RoboForex-ECN",
    "RoboForex-Prime",
    "OctaFX-Demo",
    "OctaFX-Real",
    "OctaFX-Real2",
    "FBS-Demo",
    "FBS-Real",
    "AdmiralMarkets-Demo",
    "AdmiralMarkets-Live",
    "FXCM-MT5Demo",
    "FXCM-MT5Real",
    "Tickmill-Demo",
    "Tickmill-Live",
    "ThinkMarkets-Demo",
    "ThinkMarkets-Live",
    "FPMarkets-Demo",
    "FPMarkets-Live",
    "VantageInternational-Demo",
    "VantageInternational-Live",
    "VTMarkets-Demo",
    "VTMarkets-Live",
    "Hantec-Live",
    "Hantec-Demo",
    "Ava-MT5-Demo",
    "Ava-MT5-Real",
    "MonetaMarkets-Demo",
    "MonetaMarkets-Live",
    "MetaQuotes-Demo"
]

@app.get("/api/broker-servers", response_model=List[str])
async def api_get_broker_servers(current_user: int = Depends(get_current_user)):
    """
    Returns a combined list of popular MT5 broker servers and any unique servers already saved in existing database accounts.
    """
    try:
        accounts = get_accounts(user_id=current_user)
        saved_servers = {a["server"] for a in accounts if a.get("server")}
        
        # Combine popular list with saved servers to keep unique items
        combined_servers = set(POPULAR_MT5_SERVERS) | saved_servers
        return sorted(list(combined_servers))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def api_get_accounts(current_user: int = Depends(get_current_user)):
    global ui_fetched_accounts
    ui_fetched_accounts = True
    return get_accounts(user_id=current_user)

@app.post("/api/accounts")
async def api_add_account(acc: AccountCreate, current_user: int = Depends(get_current_user)):
    success = add_account(
        login=acc.login,
        password=acc.password,
        server=acc.server,
        terminal_path=acc.terminal_path,
        risk_pct=acc.risk_pct,
        name=acc.name,
        payment_date=acc.payment_date,
        user_id=current_user
    )
    if not success:
        raise HTTPException(status_code=400, detail="Account login already exists")
    return {"status": "success", "message": f"Account {acc.login} added successfully."}

@app.post("/api/accounts/{account_id}/toggle")
async def api_toggle_account(account_id: int, request: Request, current_user: int = Depends(get_current_user)):
    account = get_account(account_id)
    if not account or account.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="Not authorized to access this account")
    data = await request.json()
    is_active = data.get("is_active", True)
    set_account_active(account_id, is_active)
    
    # If deactivating, kill executor and terminal
    if not is_active:
        terminal_path = account.get("terminal_path")
        login = account["login"]
        if terminal_path:
            try:
                terminate_executor_and_terminal(login, account_id, terminal_path)
            except Exception as e:
                print(f"Error terminating terminal on toggle: {e}")
                
    status_str = "activated" if is_active else "deactivated"
    add_log("INFO", f"dashboard_user_{current_user}", f"Account ID {account_id} has been {status_str}", user_id=current_user)
    return {"status": "success", "message": f"Account {status_str}."}

@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int, current_user: int = Depends(get_current_user)):
    account = get_account(account_id)
    if not account or account.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="Not authorized to delete this account")
    
    terminal_path = account.get("terminal_path")
    login = account["login"]
    delete_account(account_id)
    
    # If deleting, kill executor and terminal
    if terminal_path:
        try:
            terminate_executor_and_terminal(login, account_id, terminal_path)
        except Exception as e:
            print(f"Error terminating terminal on delete: {e}")
            
    return {"status": "success", "message": "Account deleted successfully."}

@app.get("/api/trades")
async def api_get_trades(current_user: int = Depends(get_current_user)):
    return get_recent_trades(50, user_id=current_user)

@app.post("/api/trades/{trade_id}/cancel")
async def api_cancel_trade(trade_id: int, current_user: int = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        trade = dict(trade)
        
        # Verify ownership
        account = get_account(trade["account_id"])
        if not account or account.get("user_id") != current_user:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this trade")
            
        if trade["status"] != "pending":
            raise HTTPException(status_code=400, detail="Only pending orders can be cancelled")
        
        conn.execute("UPDATE trades SET status = 'cancel_requested', last_updated = CURRENT_TIMESTAMP WHERE id = ?", (trade_id,))
        conn.commit()
        
        add_log("INFO", f"dashboard_user_{current_user}", f"Cancel requested for pending trade ID {trade_id} (ticket {trade['ticket']})", user_id=current_user)
        return {"status": "success", "message": "Cancel request submitted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/trades/cancel_all")
async def api_cancel_all_trades(current_user: int = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        pending_count = conn.execute("""
        SELECT COUNT(*) FROM trades t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.status = 'pending' AND a.user_id = ?
        """, (current_user,)).fetchone()[0]
        
        if pending_count == 0:
            return {"status": "success", "message": "No pending orders to cancel"}
            
        conn.execute("""
        UPDATE trades SET status = 'cancel_requested', last_updated = CURRENT_TIMESTAMP 
        WHERE status = 'pending' AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)
        """, (current_user,))
        conn.commit()
        
        add_log("INFO", f"dashboard_user_{current_user}", f"Cancel requested for all {pending_count} pending orders", user_id=current_user)
        return {"status": "success", "message": f"Cancel request submitted for all {pending_count} pending orders"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/signals")
async def api_get_signals(current_user: int = Depends(get_current_user)):
    return get_recent_signals(20, user_id=current_user)

@app.post("/api/signals")
async def api_add_manual_signal(sig: SignalCreate, current_user: int = Depends(get_current_user)):
    try:
        action = sig.action.upper().strip()
        if action not in ["BUY", "SELL", "CLOSE", "MODIFY"]:
            raise HTTPException(status_code=400, detail="Invalid action type")
            
        symbol = sig.symbol.upper().strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="Symbol is required")
            
        # Create a raw_text representation for display in the log
        parts = [f"MANUAL: {action} {symbol}"]
        if sig.entry_min is not None and sig.entry_max is not None:
            if sig.entry_min == sig.entry_max:
                parts.append(f"price {sig.entry_min}")
            else:
                parts.append(f"price ({sig.entry_min}-{sig.entry_max})")
        if sig.sl is not None:
            parts.append(f"SL {sig.sl}")
        if sig.tp1 is not None:
            parts.append(f"TP1 {sig.tp1}")
        if sig.tp2 is not None:
            parts.append(f"TP2 {sig.tp2}")
        if sig.tp3 is not None:
            parts.append(f"TP3 {sig.tp3}")
            
        raw_text = " ".join(parts)
        
        # Insert signal into DB
        signal_id = add_signal(
            telegram_msg_id=8888, # 8888 indicates a manual signal from the dashboard
            channel_id=0,
            raw_text=raw_text,
            action=action,
            symbol=symbol,
            sl=sig.sl,
            tp1=sig.tp1,
            tp2=sig.tp2,
            tp3=sig.tp3,
            entry_min=sig.entry_min,
            entry_max=sig.entry_max,
            user_id=current_user
        )
        
        add_log("INFO", f"dashboard_user_{current_user}", f"Manual signal {signal_id} ({action} {symbol}) added from dashboard UI", user_id=current_user)
        return {"status": "success", "message": "Manual signal created successfully", "signal_id": signal_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
async def api_get_logs(current_user: int = Depends(get_current_user)):
    return get_recent_logs(100, user_id=current_user)

@app.get("/api/settings")
async def api_get_settings(current_user: int = Depends(get_current_user)):
    settings = get_settings(user_id=current_user)
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
async def api_save_settings(settings: SettingsUpdate, current_user: int = Depends(get_current_user)):
    save_settings({
        "api_id": settings.api_id.strip(),
        "api_hash": settings.api_hash.strip(),
        "phone": settings.phone.strip(),
        "monitored_channels": json.dumps(settings.monitored_channels)
    }, user_id=current_user)
    return {"status": "success", "message": "Settings saved successfully."}

@app.post("/api/telegram/send_code")
async def api_telegram_send_code(payload: TelegramCodeSend, current_user: int = Depends(get_current_user)):
    phone = payload.phone.strip()
    settings = get_settings(user_id=current_user)
    api_id_str = settings.get("api_id", "")
    api_hash = settings.get("api_hash", "")
    
    if not api_id_str or not api_hash:
        raise HTTPException(status_code=400, detail="Telegram API credentials are not configured in settings.")
        
    try:
        api_id = int(api_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="API ID must be an integer.")
        
    # Build session file path (in the directory of the executable/script, not the temp folder)
    is_frozen = getattr(sys, 'frozen', False)
    base_dir = os.path.dirname(sys.executable) if is_frozen else os.path.dirname(os.path.abspath(__file__))
    session_path = os.path.abspath(os.path.join(base_dir, f"telegram_user_{current_user}"))
    
    # Instantiate client
    client = TelegramClient(session_path, api_id, api_hash)
    
    try:
        await client.connect()
        # Request code
        result = await client.send_code_request(phone)
        
        # Save client, hash and phone in-memory by current_user ID
        active_logins[current_user] = {
            "client": client,
            "hash": result.phone_code_hash,
            "phone": phone
        }
        
        add_log("INFO", f"dashboard_user_{current_user}", f"Sent verification code to {phone}", user_id=current_user)
        return {"status": "success", "message": "Code sent successfully."}
    except Exception as e:
        add_log("ERROR", f"dashboard_user_{current_user}", f"Failed to send Telegram code to {phone}: {e}", user_id=current_user)
        # Make sure to disconnect if active
        if client:
            await client.disconnect()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/login")
async def api_telegram_login(payload: TelegramLogin, current_user: int = Depends(get_current_user)):
    phone = payload.phone.strip()
    code = payload.code.strip()
    password = payload.password.strip() if payload.password else None
    
    if current_user not in active_logins or active_logins[current_user]["phone"] != phone:
        raise HTTPException(status_code=400, detail="Verification session expired or not found. Please resend code.")
        
    login_data = active_logins[current_user]
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
        save_settings({"telegram_status": "connected", "phone": phone}, user_id=current_user)
        add_log("INFO", f"dashboard_user_{current_user}", f"Successfully logged into Telegram account {phone}", user_id=current_user)
        
        # Clean up temporary storage and disconnect client
        # Note: Disconnect will let the separate listener process claim the session lock
        await client.disconnect()
        del active_logins[current_user]
        
        return {"status": "success", "message": "Logged into Telegram successfully."}
    except Exception as e:
        add_log("ERROR", f"dashboard_user_{current_user}", f"Failed to complete Telegram login for {phone}: {e}", user_id=current_user)
        # Disconnect client
        await client.disconnect()
        if current_user in active_logins:
            del active_logins[current_user]
        raise HTTPException(status_code=500, detail=str(e))
