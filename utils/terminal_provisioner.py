import os
import sys
import shutil
import hashlib
import time
import psutil

def get_project_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def terminate_executor_and_terminal(login, account_id, terminal_path):
    # 1. Terminate executor subprocess
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any('--account-id' in part for part in cmdline) and any(str(account_id) in part for part in cmdline):
                print(f"Terminating executor process for account {login} (PID {proc.info['pid']})...")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2. Terminate terminal64.exe
    target_abs = os.path.abspath(terminal_path)
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if proc.info['exe'] and os.path.abspath(proc.info['exe']) == target_abs:
                print(f"Terminating terminal process for account {login} (PID {proc.info['pid']})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def enable_experts_in_common_ini(config_dir):
    common_ini_path = os.path.join(config_dir, "common.ini")
    
    # Check if file exists
    if not os.path.exists(common_ini_path):
        # Create a basic common.ini if missing
        content = "[Experts]\r\nEnabled=1\r\n"
        try:
            with open(common_ini_path, "w", encoding="utf-16") as f:
                f.write(content)
        except Exception as e:
            print(f"Warning: Failed to create common.ini: {e}")
        return

    # Read existing content
    try:
        with open(common_ini_path, "r", encoding="utf-16") as f:
            lines = f.readlines()
    except Exception:
        # Fallback to standard open
        try:
            with open(common_ini_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return

    # Parse and update/add [Experts] section
    out_lines = []
    in_experts = False
    has_enabled = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_experts and not has_enabled:
                out_lines.append("Enabled=1\r\n")
                has_enabled = True
            if stripped == "[Experts]":
                in_experts = True
            else:
                in_experts = False
        
        if in_experts and stripped.startswith("Enabled="):
            out_lines.append("Enabled=1\r\n")
            has_enabled = True
        else:
            out_lines.append(line)
            
    # If experts section was never closed and has not been added
    if in_experts and not has_enabled:
        out_lines.append("Enabled=1\r\n")
        has_enabled = True
        
    # If [Experts] section wasn't found at all
    if "[Experts]" not in [l.strip() for l in lines]:
        out_lines.append("\r\n[Experts]\r\nEnabled=1\r\n")
        
    # Write back in UTF-16
    try:
        with open(common_ini_path, "w", encoding="utf-16") as f:
            f.writelines(out_lines)
    except Exception as e:
        print(f"Warning: Failed to write common.ini: {e}")

def find_mt5_source_dir(user_specified_path=None):
    """
    Locates the source directory containing terminal64.exe.
    Checks the user specified path first, then common program folders.
    """
    # 1. Check user specified path
    if user_specified_path:
        user_specified_path = user_specified_path.strip()
        if os.path.isfile(user_specified_path):
            src_dir = os.path.dirname(user_specified_path)
            if os.path.exists(os.path.join(src_dir, "terminal64.exe")):
                return src_dir
        elif os.path.isdir(user_specified_path):
            if os.path.exists(os.path.join(user_specified_path, "terminal64.exe")):
                return user_specified_path

    # 2. Check standard search paths
    standard_paths = [
        r"C:\Program Files\MetaTrader 5",
        r"C:\Program Files\MetaTrader 5\terminal",
        r"C:\Program Files (x86)\MetaTrader 5"
    ]
    for p in standard_paths:
        if os.path.exists(os.path.join(p, "terminal64.exe")):
            return p

    return None

def find_appdata_config_dir(terminal_exe_path):
    """
    Finds the corresponding AppData config folder where MT5 stores
    broker configuration files (like servers.dat and certificates).
    """
    install_dir = os.path.dirname(os.path.abspath(terminal_exe_path))
    # MT5 uses MD5 hash of uppercase terminal directory without trailing slash
    path_bytes = install_dir.upper().encode('utf-16le')
    hash_str = hashlib.md5(path_bytes).hexdigest().upper()
    
    appdata = os.environ.get("APPDATA")
    if appdata:
        appdata_dir = os.path.join(appdata, "MetaQuotes", "Terminal", hash_str, "config")
        if os.path.exists(appdata_dir):
            return appdata_dir
    return None

def provision_isolated_terminal(login, password, server, user_specified_path=None):
    """
    Creates an isolated MT5 directory under mt5_instances/acc_<login>,
    copies terminal64.exe, copies config files and certificates from AppData,
    and sets up startup.ini for automated login.
    Returns the absolute path to terminal64.exe.
    """
    src_dir = find_mt5_source_dir(user_specified_path)
    if not src_dir:
        raise Exception("Could not locate a valid MetaTrader 5 installation containing terminal64.exe on your system.")

    terminal_exe = os.path.join(src_dir, "terminal64.exe")

    # Get project root folder (parent of utils/)
    project_root = get_project_root()
    dest_dir = os.path.join(project_root, "mt5_instances", f"acc_{login}")
    os.makedirs(dest_dir, exist_ok=True)

    # 1. Copy executable files
    files_to_copy = ["terminal64.exe", "MetaEditor64.exe", "metatester64.exe", "Terminal.ico"]
    for file in files_to_copy:
        src_file = os.path.join(src_dir, file)
        dest_file = os.path.join(dest_dir, file)
        if os.path.exists(src_file) and not os.path.exists(dest_file):
            try:
                shutil.copy2(src_file, dest_file)
            except Exception as e:
                print(f"Warning: Failed to copy {file} from {src_file} to {dest_file}: {e}")

    # 2. Set up Config directory
    dest_config_dir = os.path.join(dest_dir, "Config")
    os.makedirs(dest_config_dir, exist_ok=True)

    # 3. Copy configuration files (servers.dat, accounts.dat, certificates)
    appdata_config = find_appdata_config_dir(terminal_exe)
    if appdata_config:
        for item in os.listdir(appdata_config):
            s_item = os.path.join(appdata_config, item)
            d_item = os.path.join(dest_config_dir, item)
            try:
                if os.path.isdir(s_item):
                    if not os.path.exists(d_item):
                        shutil.copytree(s_item, d_item)
                else:
                    shutil.copy2(s_item, d_item)
            except Exception as e:
                print(f"Warning: Failed to copy config item {item}: {e}")
    else:
        # Fallback to copy from local Config directory if it exists
        local_config = os.path.join(src_dir, "Config")
        if os.path.exists(local_config):
            for item in os.listdir(local_config):
                s_item = os.path.join(local_config, item)
                d_item = os.path.join(dest_config_dir, item)
                try:
                    if os.path.isdir(s_item):
                        if not os.path.exists(d_item):
                            shutil.copytree(s_item, d_item)
                    else:
                        shutil.copy2(s_item, d_item)
                except Exception as e:
                    print(f"Warning: Failed to copy config item {item} from local Config: {e}")

    # 4. Create startup.ini for auto-login
    startup_ini_path = os.path.join(dest_config_dir, "startup.ini")
    startup_content = f"""[Common]
Login={login}
Password={password}
Server={server}
SavePassword=1
EnableExperts=1
"""
    with open(startup_ini_path, "w", encoding="utf-8") as f:
        f.write(startup_content)

    # 5. Enable Experts (Algo Trading) in common.ini
    enable_experts_in_common_ini(dest_config_dir)

    return os.path.abspath(os.path.join(dest_dir, "terminal64.exe"))

def sync_and_provision_all_accounts():
    """
    Iterates through all accounts in the database, checks if they are provisioned
    in mt5_instances/acc_<login>, provisions them if missing, and updates their
    terminal_path in the DB to the isolated copy.
    """
    from utils.db import get_accounts, get_db_connection, add_log

    accounts = get_accounts()
    conn = get_db_connection()
    try:
        for acc in accounts:
            login = acc["login"]
            password = acc["password"]
            server = acc["server"]
            current_path = acc["terminal_path"]

            # Target path under mt5_instances
            target_path = os.path.abspath(os.path.join(
                get_project_root(), "mt5_instances", f"acc_{login}", "terminal64.exe"
            ))
            
            # Re-provision if terminal64.exe is missing OR if Config/servers.dat is missing OR if EnableExperts is not in startup.ini OR if Enabled=1 is not in common.ini
            servers_dat_path = os.path.join(os.path.dirname(target_path), "Config", "servers.dat")
            startup_ini_path = os.path.join(os.path.dirname(target_path), "Config", "startup.ini")
            common_ini_path = os.path.join(os.path.dirname(target_path), "Config", "common.ini")
            
            has_enable_experts = False
            if os.path.exists(startup_ini_path):
                try:
                    with open(startup_ini_path, "r", encoding="utf-8") as sf:
                        if "EnableExperts" in sf.read():
                            has_enable_experts = True
                except Exception:
                    pass

            has_experts_enabled = False
            if os.path.exists(common_ini_path):
                try:
                    with open(common_ini_path, "r", encoding="utf-16") as cf:
                        content = cf.read()
                        if "[Experts]" in content:
                            experts_part = content.split("[Experts]")[1]
                            if "[" in experts_part:
                                experts_part = experts_part.split("[")[0]
                            if "Enabled=1" in experts_part.replace(" ", ""):
                                has_experts_enabled = True
                except Exception:
                    pass

            should_provision = (
                not os.path.exists(target_path) or 
                not os.path.exists(servers_dat_path) or 
                not has_enable_experts or 
                not has_experts_enabled or
                os.path.abspath(current_path) != target_path
            )

            if should_provision:
                try:
                    add_log("INFO", "system", f"Provisioning isolated MT5 terminal for account {login}...", user_id=acc["user_id"])
                    # Terminate executor and terminal first to release file locks
                    terminate_executor_and_terminal(login, acc["id"], target_path)
                    time.sleep(1.0)
                    new_path = provision_isolated_terminal(login, password, server, current_path)

                    # Update terminal_path in DB
                    conn.execute("""
                        UPDATE accounts
                        SET terminal_path = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_path, acc["id"]))
                    conn.commit()
                    add_log("INFO", "system", f"Successfully provisioned isolated terminal for account {login} at {new_path}", user_id=acc["user_id"])
                except Exception as e:
                    add_log("ERROR", "system", f"Failed to provision terminal for account {login}: {e}", user_id=acc["user_id"])
                    # Update error in DB so it shows on the dashboard
                    conn.execute("""
                        UPDATE accounts
                        SET last_error = ?, connection_status = 'disconnected', last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (f"Provisioning failed: {str(e)}", acc["id"]))
                    conn.commit()
    finally:
        conn.close()
