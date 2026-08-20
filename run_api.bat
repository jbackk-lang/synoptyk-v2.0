@echo off
title Synoptyk-v2.0 -- API (Uvicorn)
color 0A
cls

:: Osobny, OPCJONALNY serwer API (FastAPI/Uvicorn) - GUI (run.bat) go
:: NIE potrzebuje do dzialania, patrz komentarz w run.bat. Uruchom to
:: tylko jesli chcesz programowy dostep do danych albo dokumentacje
:: Swagger pod http://127.0.0.1:8000/docs.

cd /d "%~dp0"

echo ============================================================
echo   SYNOPTYK-v2.0: Uruchamianie API (Uvicorn)
echo   Katalog roboczy: %cd%
echo ============================================================
echo.

set PYTHONUNBUFFERED=1

if exist "venv\Scripts\activate.bat" (
    echo [OK] Aktywacja venv...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [OK] Aktywacja .venv...
    call .venv\Scripts\activate.bat
) else (
    echo [INFO] Uzywanie systemowej instalacji Pythona.
)

echo.
echo Weryfikacja i instalacja pakietow pip...
python -m pip install --upgrade pip --disable-pip-version-check
python -m pip install fastapi uvicorn pandas numpy requests

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Nie udalo sie zainstalowac wymaganych pakietow.
    pause
    exit /b 1
)

if not exist "api\main.py" (
    echo [BLAD] Nie znaleziono pliku "%cd%\api\main.py"
    echo         Sprawdz, czy ten .bat lezy w tym samym folderze co api\.
    pause
    exit /b 1
)

echo.
echo Interfejs API: http://127.0.0.1:8000
echo Dokumentacja Swagger: http://127.0.0.1:8000/docs
echo (Ctrl+C aby zatrzymac)
echo.

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

pause
