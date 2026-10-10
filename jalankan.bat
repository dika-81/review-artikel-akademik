@echo off
rem Menjalankan aplikasi secara lokal lalu membuka tunnel ngrok.
rem Prasyarat: .venv sudah dibuat dan requirements.txt sudah terinstal.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment belum ada. Jalankan dulu:
    echo   py -3.12 -m venv .venv   ^(atau: python -m venv .venv^)
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

start "Flask" cmd /k ".venv\Scripts\python.exe app.py"

timeout /t 5

start "ngrok" cmd /k "ngrok http 5000"
