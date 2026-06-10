# Production Deployment & Optimization Guide

This guide describes how to deploy the Telegram-to-MT5 copier bot on a low-cost Ubuntu VPS (2 vCPU, 4GB RAM) running headless MT5 terminals inside a Wine environment.

---

## 1. Operating System Preparation (Ubuntu)

Log in to your Ubuntu Server and update packages:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y software-properties-common wget curl git build-essential
```

### Enable 32-bit Architecture & Add WineHQ Repository

Since Wine works best with x86/x64 libraries, add the architecture and Wine signing keys:

```bash
sudo dpkg --add-architecture i386
sudo mkdir -pm755 /etc/apt/keyrings
sudo wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/winebuilds/winehq.key
wget -NC https://dl.winehq.org/winebuilds/ubuntu/dists/$(lsb_release -cs)/winehq-$(lsb_release -cs).sources
sudo mv winehq-*.sources /etc/apt/sources.list.d/
```

Update repositories and install Wine Stable:

```bash
sudo apt update
sudo apt install --install-recommends winehq-stable -y
```

### Setup Xvfb (Virtual Framebuffer)

MetaTrader 5 requires a graphical display to initialize and run, even when operated headlessly via Python. Xvfb creates a virtual display in memory:

```bash
sudo apt install xvfb x11vnc x11-apps -y
```

---

## 2. Python Setup inside Wine

To communicate with the MT5 terminal via the Python API, **Python must run inside the exact same Wine prefix** as the MT5 terminal.

1. **Create isolated Wine Prefix**:
   ```bash
   export WINEPREFIX=~/.mt5_prefix
   export WINEARCH=win64
   winecfg  # Click OK on any popups to initialize the environment
   ```

2. **Download & Install Windows Python inside Wine**:
   ```bash
   wget https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
   wine python-3.10.11-amd64.exe /quiet InstallAllUsers=1 PrependPath=1
   ```

3. **Install python packages inside Wine**:
   ```bash
   wine python -m pip install --upgrade pip
   wine python -m pip install telethon fastapi uvicorn psutil MetaTrader5
   ```

---

## 3. MetaTrader 5 Terminal Installation

1. **Download MT5 Installer**:
   ```bash
   wget https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
   ```

2. **Run MT5 Installer under Wine**:
   ```bash
   xvfb-run --server-args="-screen 0 1024x768x24" wine mt5setup.exe /portable
   ```
   *Follow the graphical prompt in your X11 redirection, or complete the installation.*
   The terminal executable will usually be located in:
   `~/.mt5_prefix/drive_c/Program Files/MetaTrader 5/terminal64.exe`

### Running Multiple MT5 Accounts (Low Latency / RAM Isolation)

For production scalability (10-20 accounts), copy the installed MetaTrader folder into separate directories inside Wine:

```bash
cp -r "$WINEPREFIX/drive_c/Program Files/MetaTrader 5" "$WINEPREFIX/drive_c/Program Files/MT5_Acc_1"
cp -r "$WINEPREFIX/drive_c/Program Files/MetaTrader 5" "$WINEPREFIX/drive_c/Program Files/MT5_Acc_2"
```

Start each terminal with the `/portable` flag:

```bash
xvfb-run -a wine "$WINEPREFIX/drive_c/Program Files/MT5_Acc_1/terminal64.exe" /portable
```

---

## 4. VPS & MetaTrader Resource Optimizations

Standard MT5 installations consume ~150-200MB RAM. With these optimization steps, you can reduce usage to **40-70MB RAM per terminal**, allowing up to 30 terminals on a 4GB VPS.

### MT5 Terminal GUI Optimizations
Inside each MetaTrader terminal (using an X11 forwarding viewer or by editing the `common.ini` configuration):
1. **Close All Charts**: Close every open chart window. This stops MT5 from rendering graphics and loading indicator histories into RAM.
2. **Disable News**: Go to *Tools -> Options -> Server* and uncheck **Enable News**.
3. **Limit Max Chart Bars**: Go to *Tools -> Options -> Charts* and set **Max bars in chart** to `5000`.
4. **Disable Audio Events**: Go to *Tools -> Options -> Events* and uncheck **Enable**.

### Edit Configuration (`common.ini`) Directly
You can automate this by adding/modifying these lines in the terminal directory config (`/portable` data folder `/config/common.ini`):
```ini
[Charts]
MaxBars=5000
[News]
Enable=0
[Sound]
Enable=0
```

---

## 5. Supervisor Service Configuration

Supervisor keeps the orchestrator running in the background and restarts it automatically if it crashes.

1. **Install Supervisor**:
   ```bash
   sudo apt install supervisor -y
   ```

2. **Create Supervisor Config**:
   Create `/etc/supervisor/conf.d/mt5_copier.conf`:

   ```ini
   [program:mt5_copier]
   command=xvfb-run --server-args="-screen 0 1024x768x24" wine python main.py
   directory=/home/ubuntu/signal-bot-mt5
   autostart=true
   autorestart=true
   user=ubuntu
   environment=WINEPREFIX="/home/ubuntu/.mt5_prefix",WINEARCH="win64",DISPLAY=":99"
   stdout_logfile=/var/log/mt5_copier.stdout.log
   stderr_logfile=/var/log/mt5_copier.stderr.log
   ```

3. **Load and Start Program**:
   ```bash
   sudo supervisorctl reread
   sudo supervisorctl update
   sudo supervisorctl start mt5_copier
   ```

---

## 6. Nginx Web Server & Reverse Proxy Setup

Secure access to the copier dashboard using Nginx.

1. **Install Nginx**:
   ```bash
   sudo apt install nginx -y
   ```

2. **Configure Nginx Site**:
   Create `/etc/nginx/sites-available/mt5_copier`:

   ```nginx
   server {
       listen 80;
       server_name your_vps_ip_or_domain;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }
   }
   ```

3. **Enable Site & Restart Nginx**:
   ```bash
   sudo ln -s /etc/nginx/sites-available/mt5_copier /etc/nginx/sites-enabled/
   sudo rm /etc/nginx/sites-enabled/default
   sudo systemctl restart nginx
   ```

---

## 7. Performance & Memory Projections

| Account Count | MT5 RAM Usage (Optimized) | Python Worker RAM Usage | Total RAM Consumed |
| :--- | :--- | :--- | :--- |
| **5 Accounts** | 250 MB | 85 MB | **~335 MB** |
| **10 Accounts** | 500 MB | 170 MB | **~670 MB** |
| **20 Accounts** | 1.0 GB | 340 MB | **~1.34 GB** |
| **50 Accounts** | 2.5 GB | 850 MB | **~3.35 GB** (Limits of 4GB VPS) |

> [!TIP]
> Keep an eye on system resources directly on the dashboard homepage. If memory exceeds 85%, clean up old Wine cache using `wineboot -k` or restart supervisor processes.
