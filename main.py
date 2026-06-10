import os
import sys
import time
import subprocess
import threading
import signal
import uvicorn
from utils.db import init_db, get_accounts, get_settings, add_log

# Track active subprocesses
active_executors = {} # {account_id: subprocess.Popen}
telegram_listener_proc = None # subprocess.Popen
server_thread = None

# Cleanup on exit
def cleanup(signum=None, frame=None):
    global telegram_listener_proc, active_executors
    print("\nShutting down copier application, cleaning up subprocesses...")
    
    # Terminate Telegram listener
    if telegram_listener_proc:
        try:
            telegram_listener_proc.terminate()
            telegram_listener_proc.wait(timeout=2)
        except Exception:
            try:
                telegram_listener_proc.kill()
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
        uvicorn.run("dashboard:app", host="0.0.0.0", port=8000, log_level="warning")
    except Exception as e:
        print(f"Web server exception: {e}", file=sys.stderr)

def main():
    global telegram_listener_proc, active_executors, server_thread
    
    print("=========================================")
    print("   ANTIGRAVITY MT5 COPIER ORCHESTRATOR   ")
    print("=========================================")
    
    # 1. Initialize SQLite Database
    init_db()
    add_log("INFO", "system", "System orchestrator started. SQLite Database initialized.")
    
    # 2. Start Web Dashboard Server inside daemon thread
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()
    print("FastAPI Dashboard initialized on http://localhost:8000")
    
    # 3. Subprocesses monitor loop
    while True:
        try:
            settings = get_settings()
            accounts = get_accounts()
            
            # --- Manage Telegram Listener Subprocess ---
            tel_status = settings.get("telegram_status", "disconnected")
            api_id = settings.get("api_id", "")
            api_hash = settings.get("api_hash", "")
            
            should_run_telegram = (tel_status in ["connected", "auth_required"]) and api_id and api_hash
            
            if should_run_telegram:
                if telegram_listener_proc is None or telegram_listener_proc.poll() is not None:
                    if telegram_listener_proc is not None:
                        exit_code = telegram_listener_proc.poll()
                        add_log("WARNING", "system", f"Telegram listener process exited unexpectedly with code {exit_code}. Restarting...")
                    add_log("INFO", "system", "Launching Telegram listener subprocess...")
                    telegram_listener_proc = subprocess.Popen([
                        sys.executable, "telegram_listener.py"
                    ])
            else:
                if telegram_listener_proc is not None:
                    add_log("INFO", "system", "Stopping Telegram listener subprocess...")
                    try:
                        telegram_listener_proc.terminate()
                        telegram_listener_proc.wait(timeout=2)
                    except Exception:
                        try:
                            telegram_listener_proc.kill()
                        except Exception:
                            pass
                    telegram_listener_proc = None
                    
            # --- Manage MT5 Executor Worker Subprocesses ---
            active_db_account_ids = []
            
            for acc in accounts:
                acc_id = acc["id"]
                login = acc["login"]
                is_active = acc["is_active"]
                
                if is_active:
                    active_db_account_ids.append(acc_id)
                    # Launch executor if not running
                    if acc_id not in active_executors or active_executors[acc_id].poll() is not None:
                        if acc_id in active_executors:
                            exit_code = active_executors[acc_id].poll()
                            add_log("WARNING", "system", f"Executor process for account {login} exited unexpectedly with code {exit_code}. Restarting...")
                            
                        add_log("INFO", "system", f"Launching MT5 executor subprocess for account {login}...")
                        active_executors[acc_id] = subprocess.Popen([
                            sys.executable, "mt5_executor.py", "--account-id", str(acc_id)
                        ])
                else:
                    # Account deactivated, stop executor
                    if acc_id in active_executors:
                        add_log("INFO", "system", f"Stopping executor process for account {login} (deactivated)...")
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
