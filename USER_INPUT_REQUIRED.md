# How to Run & Configuration Requirements

You do **NOT** need to edit any code files to configure your accounts, channels, or keys. Everything is configured dynamically through the web dashboard.

Below are the details of what is required from you, followed by instructions on how to start the project.

---

## 1. What Details You Need to Prepare

Before starting, gather the following configuration details:

### A. Telegram Configuration (For Signal Listening)
1. **Telegram API ID** and **API Hash**:
   - Go to [my.telegram.org](https://my.telegram.org) and log in.
   - Go to **API development tools**.
   - Create a new application (you can name it "MT5Copier").
   - Copy the **App api_id** (integer) and **App api_hash** (string).
2. **Phone Number**: The phone number associated with your Telegram account (must include country code, e.g., `+923001234567`).
3. **Monitored Channels**: The usernames or ID numbers of the Telegram signal channels you want to monitor:
   - For public channels, use the username (e.g., `my_forex_signals_group`).
   - For private channels, use the channel ID (e.g., `-1001234567890`).
   - *Tip: If you leave this list empty, the bot will parse signals from ALL channels/groups your account is currently joined in.*

### B. MetaTrader 5 Configuration (For Execution)
For **each** MT5 account you want to copy trades to:
1. **Login ID**: Your MT5 account number (e.g., `50123456`).
2. **Password**: The password for your MT5 account.
3. **Broker Server**: The exact server name of your broker (e.g., `ICMarkets-Demo` or `Pepperstone-MT5-Demo`).
4. **Terminal Path**: The absolute file path to the `terminal64.exe` program of the MT5 installation for that account:
   - On Windows: `C:\Program Files\MetaTrader 5\terminal64.exe`
   - On Linux/Wine: Path relative to Wine prefix `C:\Program Files\MetaTrader 5\terminal64.exe`
5. **Risk Percentage**: The percentage of the account balance you want to risk per trade (e.g., `1.0` for 1% risk).

---

## 2. How to Run the Project (Locally / Dev Mode)

Follow these steps to run the application on your computer:

### Step 1: Install Python Dependencies
Open your command prompt or terminal in the `signal-bot-mt5` folder and install the required packages:

```bash
pip install -r requirements.txt
```

### Step 2: Start the Orchestrator
Run the main script:

```bash
python main.py
```

This will initialize the SQLite database (`trading_bot.db`), start the FastAPI dashboard backend, and begin monitoring connections.

### Step 3: Open the Dashboard
Open your web browser and navigate to:
```
http://localhost:8000
```

---

## 3. Configuration Step-by-Step on the Dashboard

Once the dashboard is open in your browser:

1. **Setup Telegram**:
   - Click the **Setup Telegram** button in the top right corner.
   - Enter your **API ID**, **API Hash**, **Phone Number**, and the names of the **Monitored Channels** (comma-separated).
   - Click **Save Config**.
   - Under the *Initialize Telegram Session* section, enter your phone number and click **Send Code**.
   - A verification code will be sent to your Telegram app or SMS. Enter that code in the *Login Code* box (and your 2FA password if enabled) and click **Confirm Code**.
   - The status indicator at the top will change to **Telegram: Connected**.

2. **Add MT5 Accounts**:
   - Click **+ Add MT5 Account**.
   - Input your MT5 account **Login ID**, **Password**, **Server**, **Terminal Path**, and **Risk Percentage** (default 1.0).
   - Click **Save Account**.
   - The orchestrator will automatically launch the worker process for this account, open the MT5 terminal, log in, and sync the account balance and equity.
