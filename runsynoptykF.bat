@echo off
title SYNOPTYK-F Launcher

echo ===================================================
echo   SYNOPTYK-F Web Service and API Launcher
echo ===================================================
echo.

:: 1. Przejscie do katalogu skryptu
cd /d "%~dp0"

:: 2. Weryfikacja i instalacja zaleznosci
echo [1/2] Sprawdzanie i instalacja pakietow Python...
python -m pip install --quiet fastapi uvicorn pydantic requests

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Nie udalo sie zainstalowac pakietow. Sprawdz czy Python jest w PATH.
    pause
    exit /b %ERRORLEVEL%
)

:: 3. Uruchomienie serwera API i Dashboardu WWW
echo [2/2] Uruchamianie serwera pod adresem http://127.0.0.1:8000 ...
echo.
echo Nacisnij CTRL+C, aby zatrzymac serwer.
echo ---------------------------------------------------

python -m uvicorn main_api:app --host 127.0.0.1 --port 8000 --reload

pause