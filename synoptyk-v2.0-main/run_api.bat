@echo off
title Synoptyk-v2.0 -- API (Uvicorn)
color 0A
cls

:: Osobny, OPCJONALNY serwer API (FastAPI/Uvicorn) - GUI (run.bat) go
:: NIE potrzebuje do dzialania, patrz komentarz w run.bat. Uruchom to
:: tylko jesli chcesz programowy dostep do danych albo dokumentacje
:: Swagger pod http://127.0.0.1:8010/docs.
::
:: ZMIENIONE: port przestawiony z 8000 na 8010 - 8000 to bardzo czesto
:: uzywany domyslny port (inne lokalne serwery/API czesto go zajmuja),
:: co powodowalo, ze w przegladarce pod tym adresem pokazywal sie
:: WCZESNIEJ juz dzialajacy, zupelnie inny program, a nie to API.
:: Ten skrypt uruchamia WYLACZNIE plik api/main.py z tego repo
:: (app = FastAPI(title="Synoptyk API v2.0")) - jesli mimo zmiany portu
:: dalej widac cos innego, ponizszy netstat pokaze, co realnie siedzi
:: na tym porcie.

cd /d "%~dp0"

echo ============================================================
echo   SYNOPTYK-v2.0: Uruchamianie API (Uvicorn)
echo   Katalog roboczy: %cd%
echo ============================================================
echo.

echo Sprawdzanie, czy port 8010 jest juz zajety...
netstat -ano | findstr ":8010" >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [UWAGA] Port 8010 jest JUZ zajety przez inny proces - to on
    echo         bedzie odpowiadal w przegladarce, nie ten skrypt:
    netstat -ano | findstr ":8010"
    echo         Ostatnia liczba w linii to PID procesu. Sprawdz go w
    echo         Menedzerze zadan ^(zakladka Szczegoly^) i zamknij, albo
    echo         zmien port w tym pliku ^(run_api.bat^) na inny.
    echo.
    pause
)

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
echo Interfejs API: http://127.0.0.1:8010
echo Dokumentacja Swagger: http://127.0.0.1:8010/docs
echo (Ctrl+C aby zatrzymac)
echo.

python -m uvicorn api.main:app --host 127.0.0.1 --port 8010 --reload

pause
