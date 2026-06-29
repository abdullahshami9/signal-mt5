import os
import sys
import time
import subprocess
import threading
import signal
import uvicorn

# Argument routing for PyInstaller packaged subprocess execution
if "--user-id" in sys.argv:
    import asyncio
    import telegram_listener
    asyncio.run(telegram_listener.main())
    sys.exit(0)

if "--account-id" in sys.argv:
    import mt5_executor
    mt5_executor.main()
    sys.exit(0)

from utils.db import init_db, get_accounts, get_settings, add_log, get_all_users

# Track active subprocesses
active_executors = {} # {account_id: subprocess.Popen}
active_listeners = {} # {user_id: subprocess.Popen}
server_thread = None

# Cleanup on exit
def cleanup(signum=None, frame=None):
    global active_listeners, active_executors
    print("\nShutting down copier application, cleaning up subprocesses...")
    
    # Terminate all Telegram listeners
    for user_id, proc in list(active_listeners.items()):
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
                
    # Terminate all MT5 executors
    for acc_id, proc in list(active_executors.items()):
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
                
    print("All subprocesses cleaned up. Exit.")
    sys.exit(0)

# Register shutdown handlers
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def run_web_server():
    """
    Runs FastAPI dashboard backend on port 8000.
    """
    try:
        from dashboard import app
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    except Exception as e:
        print(f"Web server exception: {e}", file=sys.stderr)

def main():
    global active_listeners, active_executors, server_thread
    
    print("=========================================")
    print("   QUANTHROPIC.DEV MT5 COPIER ORCHESTRATOR   ")
    print("=========================================")
    
    # 1. Initialize MySQL Database
    init_db()
    add_log("INFO", "system", "System orchestrator started. MySQL Database initialized.")
    
    # 2. Start Web Dashboard Server inside daemon thread
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()
    print("FastAPI Dashboard initialized on http://localhost:8000")
    
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    
    # 3. Subprocesses monitor loop
    while True:
        try:
            import dashboard
            if not getattr(dashboard, "ui_fetched_accounts", False):
                if not getattr(main, "_waiting_logged", False):
                    print("Waiting for user to log in and load accounts on the web UI...")
                    main._waiting_logged = True
                time.sleep(1.0)
                continue

            # --- Manage Telegram Listener Subprocesses ---
            active_user_ids = []
            try:
                users = get_all_users()
            except Exception as e:
                users = []
                add_log("ERROR", "system", f"Failed to retrieve users: {e}")
                
            for user in users:
                user_id = user["id"]
                active_user_ids.append(user_id)
                user_settings = get_settings(user_id=user_id)
                tel_status = user_settings.get("telegram_status", "disconnected")
                api_id = user_settings.get("api_id", "")
                api_hash = user_settings.get("api_hash", "")
                
                should_run_telegram = (tel_status in ["connected", "auth_required"]) and api_id and api_hash
                
                if should_run_telegram:
                    if user_id not in active_listeners or active_listeners[user_id].poll() is not None:
                        if user_id in active_listeners:
                            exit_code = active_listeners[user_id].poll()
                            add_log("WARNING", "system", f"Telegram listener process exited unexpectedly with code {exit_code}. Restarting...", user_id=user_id)
                        add_log("INFO", "system", f"Launching Telegram listener subprocess for user {user_id}...", user_id=user_id)
                        is_frozen = getattr(sys, 'frozen', False)
                        cmd = [sys.executable, "--user-id", str(user_id)] if is_frozen else [sys.executable, "main.py", "--user-id", str(user_id)]
                        active_listeners[user_id] = subprocess.Popen(cmd)
                else:
                    if user_id in active_listeners:
                        add_log("INFO", "system", f"Stopping Telegram listener subprocess for user {user_id}...", user_id=user_id)
                        proc = active_listeners.pop(user_id)
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                                
            # Terminate listeners for users deleted from database
            for user_id in list(active_listeners.keys()):
                if user_id not in active_user_ids:
                    add_log("INFO", "system", f"Stopping Telegram listener subprocess for deleted user {user_id}...")
                    proc = active_listeners.pop(user_id)
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    
            # --- Manage MT5 Executor Worker Subprocesses ---
            try:
                from utils.terminal_provisioner import sync_and_provision_all_accounts
                sync_and_provision_all_accounts()
            except Exception as e:
                add_log("ERROR", "system", f"Failed to sync and provision terminals: {e}")
                
            accounts = get_accounts() # Fetch fresh accounts after provisioning
            active_db_account_ids = []
            
            for acc in accounts:
                acc_id = acc["id"]
                login = acc["login"]
                is_active = acc["is_active"]
                user_id = acc["user_id"]
                
                if is_active:
                    active_db_account_ids.append(acc_id)
                    # Launch executor if not running
                    if acc_id not in active_executors or active_executors[acc_id].poll() is not None:
                        if acc_id in active_executors:
                            exit_code = active_executors[acc_id].poll()
                            add_log("WARNING", "system", f"Executor process for account {login} exited unexpectedly with code {exit_code}. Restarting...", user_id=user_id)
                            
                        add_log("INFO", "system", f"Launching MT5 executor subprocess for account {login}...", user_id=user_id)
                        is_frozen = getattr(sys, 'frozen', False)
                        cmd = [sys.executable, "--account-id", str(acc_id)] if is_frozen else [sys.executable, "main.py", "--account-id", str(acc_id)]
                        active_executors[acc_id] = subprocess.Popen(cmd)
                else:
                    # Account deactivated, stop executor
                    if acc_id in active_executors:
                        add_log("INFO", "system", f"Stopping executor process for account {login} (deactivated)...", user_id=user_id)
                        proc = active_executors.pop(acc_id)
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                                
            # Terminate executors for accounts deleted from the database
            for acc_id in list(active_executors.keys()):
                if acc_id not in active_db_account_ids:
                    # We can find user_id from the accounts if it is still in the local memory, or pass None
                    add_log("INFO", "system", f"Stopping executor process for account ID {acc_id} (deleted)...")
                    proc = active_executors.pop(acc_id)
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                            
            # Check for changes/crashes every 3 seconds
            time.sleep(3.0)
            
        except KeyboardInterrupt:
            cleanup()
        except Exception as e:
            print(f"Error in orchestrator loop: {e}", file=sys.stderr)
            time.sleep(3.0)

if __name__ == "__main__":
    main()
