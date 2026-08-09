@echo off
rem Chrome executes this batch file when connecting to Native Messaging.
rem We run python to execute bridge_launcher.py.
rem We check if code/.venv exists to run with that Python interpreter, else fallback.

set CURRENT_DIR=%~dp0
if exist "%CURRENT_DIR%..\code\.venv\Scripts\python.exe" (
    "%CURRENT_DIR%..\code\.venv\Scripts\python.exe" "%CURRENT_DIR%bridge_launcher.py" %*
) else (
    python "%CURRENT_DIR%bridge_launcher.py" %*
)
