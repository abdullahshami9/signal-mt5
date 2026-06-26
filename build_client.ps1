# ====================================================================
#              QUANTHROPIC.DEV CLIENT BUILD & PACKAGING SCRIPT
# ====================================================================
# This script compiles the python codebase into a single standalone
# executable for distribution to third-party clients/vendors.

$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   QUANTHROPIC.DEV CLIENT COMPILER STARTING...   " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Ensure PyInstaller is installed
Write-Host "[1/5] Checking PyInstaller installation..." -ForegroundColor Yellow
$pyinstallerCheck = pip show pyinstaller
if ($null -eq $pyinstallerCheck -or $pyinstallerCheck -eq "") {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
} else {
    Write-Host "PyInstaller is already installed." -ForegroundColor Green
}

# 2. Clean previous build folders
Write-Host "[2/5] Cleaning up old build folders..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Path "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item -Path "dist" -Recurse -Force }
if (Test-Path "Quanthropic-Client.spec") { Remove-Item -Path "Quanthropic-Client.spec" -Force }

# 3. Compile application using PyInstaller
Write-Host "[3/5] Compiling application with PyInstaller (this may take a minute)..." -ForegroundColor Yellow
# --add-data "templates;templates" packages the templates folder inside the executable
pyinstaller --onefile --add-data "templates;templates" --hidden-import="numpy" --hidden-import="numpy._core" --hidden-import="numpy._core.multiarray" --hidden-import="numpy._core._multiarray_umath" --hidden-import="numpy._core._multiarray_tests" --hidden-import="numpy._core.umath" --hidden-import="numpy._core.numerictypes" --name "Quanthropic-Client" main.py

# 4. Create vendor_transfer folder
Write-Host "[4/5] Preparing vendor_transfer packaging directory..." -ForegroundColor Yellow
$transferDir = "vendor_transfer"
if (-not (Test-Path $transferDir)) {
    New-Item -ItemType Directory -Path $transferDir | Out-Null
} else {
    if (Test-Path "$transferDir/Quanthropic-Client.exe") {
        Remove-Item -Path "$transferDir/Quanthropic-Client.exe" -Force
    }
}

# 5. Copy built files to vendor_transfer
Write-Host "[5/5] Copying compiled client binary and writing distribution files..." -ForegroundColor Yellow
Copy-Item -Path "dist/Quanthropic-Client.exe" -Destination "$transferDir/Quanthropic-Client.exe" -Force

# Create Start-Software.bat launcher
$batContent = @"
@echo off
title Quanthropic.dev MT5 Copier Launching...
echo ==========================================================
echo           QUANTHROPIC.DEV MT5 COPIER CLIENT
echo ==========================================================
echo.
echo Launching the application database and web dashboard...
echo Please do not close this window while using the software.
echo.
"%~dp0Quanthropic-Client.exe"
pause
"@
Set-Content -Path "$transferDir/Start-Software.bat" -Value $batContent
Write-Host "Created Start-Software.bat launcher." -ForegroundColor Green

# Create a template env file demonstrating overrides
$envTemplate = @"
# ====================================================================
# QUANTHROPIC.DEV CLIENT ENVIRONMENT OVERRIDES
# ====================================================================
# The Quanthropic Client has secure default AWS database connection parameters
# built directly into the executable.
#
# If you want to override the default database host, port, or credentials,
# rename this file to ".env" and set the corresponding values below.
# Otherwise, you can safely delete or ignore this file.
# ====================================================================

# Set to True to override and use production AWS credentials defined below, 
# or set to False to override and use local MySQL credentials.
# PROD_DB=True

# Custom Production Database Configuration
# DB_HOST_PROD="your-aws-db-host"
# DB_PORT_PROD=3306
# DB_USER_PROD="your-db-username"
# DB_PASSWORD_PROD="your-db-password"
# DB_NAME_PROD="your-db-name"

# Custom Local Database Configuration (if PROD_DB=False)
# DB_HOST_LOCAL="localhost"
# DB_PORT_LOCAL=3306
# DB_USER_LOCAL="root"
# DB_PASSWORD_LOCAL="your-local-password"
# DB_NAME_LOCAL="trading_bot"
"@
Set-Content -Path "$transferDir/.env.example" -Value $envTemplate
Write-Host "Created .env.example configuration template." -ForegroundColor Green

# Create README.txt instructions
$readmeContent = @"
====================================================================
               QUANTHROPIC.DEV MT5 COPIER CLIENT
====================================================================

Instructions for Running the Software:

1. Copy the entire "vendor_transfer" folder to any location on your PC.
2. Double-click the "Start-Software.bat" file (or "Quanthropic-Client.exe" directly) to run the software.
3. This will initialize the local database listener and automatically open the trading web dashboard in your default browser at http://localhost:8000.
4. Keep the console window open while using the software. Closing it will stop the system.

Note:
- No local database or python installation is required on your PC.
- The software connects securely and directly to our centralized cloud database backend.
====================================================================
"@
Set-Content -Path "$transferDir/README.txt" -Value $readmeContent
Write-Host "Created README.txt instructions." -ForegroundColor Green

# Optional cleanup of PyInstaller workspace
if (Test-Path "build") { Remove-Item -Path "build" -Recurse -Force }
if (Test-Path "Quanthropic-Client.spec") { Remove-Item -Path "Quanthropic-Client.spec" -Force }

Write-Host "==================================================" -ForegroundColor Green
Write-Host "   BUILD SUCCESSFUL!                             " -ForegroundColor Green
Write-Host "   Package is located in folder: ./vendor_transfer " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
