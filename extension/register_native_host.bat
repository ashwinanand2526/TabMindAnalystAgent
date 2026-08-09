@echo off
setlocal EnableDelayedExpansion

echo ========================================================
echo Tab Researcher - Native Messaging Host Registrar
echo ========================================================
echo.

set EXT_ID=%1

if "%EXT_ID%"=="" (
    echo [ERROR] Please provide your Chrome Extension ID as an argument.
    echo.
    echo How to find it:
    echo 1. Open Chrome and go to: chrome://extensions
    echo 2. Enable 'Developer mode' in the top right.
    echo 3. Click 'Load unpacked' and select the 'extension' folder of this project.
    echo 4. Copy the 32-character ID (e.g., hgnbflkghkppodccenimopifnffofbii)
    echo 5. Run this script again:
    echo    register_native_host.bat YOUR_EXTENSION_ID
    echo.
    goto :EOF
)

rem Get absolute path of current directory with trailing backslash removed
set "CURRENT_DIR=%~dp0"
set "CURRENT_DIR=!CURRENT_DIR:~0,-1!"

rem Replace backslashes with double-backslashes for JSON escaping
set "ESCAPED_DIR=!CURRENT_DIR:\=\\!"

echo [INFO] Extension ID: %EXT_ID%
echo [INFO] Absolute Directory: %CURRENT_DIR%
echo.

rem Generate the com.tabresearcher.bridge_launcher.json file
set "MANIFEST_PATH=%CURRENT_DIR%\com.tabresearcher.bridge_launcher.json"
set "ESCAPED_MANIFEST_PATH=!MANIFEST_PATH:\=\\!"

(
echo {
echo   "name": "com.tabresearcher.bridge_launcher",
echo   "description": "Tab Researcher Bridge Auto-Starter Host",
echo   "path": "!ESCAPED_DIR!\\launch_bridge.bat",
echo   "type": "stdio",
echo   "allowed_origins": [
echo     "chrome-extension://!EXT_ID!/"
echo   ]
echo }
) > "%MANIFEST_PATH%"

echo [INFO] Manifest generated at: %MANIFEST_PATH%

rem Add the registry key to Current User
set "REG_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\com.tabresearcher.bridge_launcher"
reg add "%REG_KEY%" /ve /t REG_SZ /d "%MANIFEST_PATH%" /f >nul

if %errorlevel% equ 0 (
    echo [SUCCESS] Windows Registry successfully updated!
    echo [SUCCESS] Registry Key: %REG_KEY%
    echo [SUCCESS] Value: %MANIFEST_PATH%
    echo.
    echo The Chrome Extension is now configured to auto-start the FastAPI bridge.
) else (
    echo [ERROR] Failed to write to the Windows Registry.
    echo Try running this batch script as an Administrator.
)

echo.
pause
