import os
import shutil

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

def provision_isolated_terminal(login, password, server, user_specified_path=None):
    """
    Creates an isolated MT5 directory under mt5_instances/acc_<login>,
    copies terminal64.exe and other executables, and sets up startup.ini.
    Returns the absolute path to terminal64.exe.
    """
    src_dir = find_mt5_source_dir(user_specified_path)
    if not src_dir:
        raise Exception("Could not locate a valid MetaTrader 5 installation containing terminal64.exe on your system.")

    # Get project root folder (parent of utils/)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dest_dir = os.path.join(project_root, "mt5_instances", f"acc_{login}")
    os.makedirs(dest_dir, exist_ok=True)

    # Copy files
    files_to_copy = ["terminal64.exe", "MetaEditor64.exe", "metatester64.exe", "Terminal.ico"]
    for file in files_to_copy:
        src_file = os.path.join(src_dir, file)
        dest_file = os.path.join(dest_dir, file)
        if os.path.exists(src_file) and not os.path.exists(dest_file):
            try:
                shutil.copy2(src_file, dest_file)
            except Exception as e:
                # Log or print warning, continue with other files
                print(f"Warning: Failed to copy {file} from {src_file} to {dest_file}: {e}")

    # Set up Config/startup.ini
    config_dir = os.path.join(dest_dir, "Config")
    os.makedirs(config_dir, exist_ok=True)

    startup_ini_path = os.path.join(config_dir, "startup.ini")
    startup_content = f"""[Common]
Login={login}
Password={password}
Server={server}
SavePassword=1
"""
    with open(startup_ini_path, "w", encoding="utf-8") as f:
        f.write(startup_content)

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
                os.path.dirname(__file__), "..", "mt5_instances", f"acc_{login}", "terminal64.exe"
            ))

            # If the target file does not exist, or the DB path is not set to the target path
            if not os.path.exists(target_path) or os.path.abspath(current_path) != target_path:
                try:
                    add_log("INFO", "system", f"Provisioning isolated MT5 terminal for account {login}...")
                    new_path = provision_isolated_terminal(login, password, server, current_path)

                    # Update terminal_path in DB
                    conn.execute("""
                        UPDATE accounts
                        SET terminal_path = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_path, acc["id"]))
                    conn.commit()
                    add_log("INFO", "system", f"Successfully provisioned isolated terminal for account {login} at {new_path}")
                except Exception as e:
                    add_log("ERROR", "system", f"Failed to provision terminal for account {login}: {e}")
                    # Update error in DB so it shows on the dashboard
                    conn.execute("""
                        UPDATE accounts
                        SET last_error = ?, connection_status = 'disconnected', last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (f"Provisioning failed: {str(e)}", acc["id"]))
                    conn.commit()
    finally:
        conn.close()
