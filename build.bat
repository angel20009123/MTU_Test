@echo off
cd /d "%~dp0"
python build.py
if errorlevel 1 (
    echo Build failed. Check the log above. PyInstaller must be installed, and the output EXE must be closed.
    pause
    exit /b 1
)
