@echo off
title Synoptyk-v2.0 -- TIMDR Full Performance Mode
color 0A
cls

:: Zawsze pracuj w katalogu, w ktorym faktycznie lezy ten plik .bat,
:: niezaleznie od tego, skad zostal uruchomiony (skrot, terminal, itp.)
cd /d "%~dp0"

echo ============================================================
echo   SYNOPTYK-v2.0: Uruchamianie GUI (jedno okno)
echo   Katalog roboczy: %cd%
echo   (osobne API/Swagger: uruchom run_api.bat - GUI go nie potrzebuje)
echo ============================================================
echo.

:: 1. ZDJECIE LIMITOW SYSTEMOWYCH I WATKOWYCH
set PYTHONUNBUFFERED=1
set OMP_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set MKL_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set OPENBLAS_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set VECLIB_MAXIMUM_THREADS=%NUMBER_OF_PROCESSORS%
set NUMEXPR_NUM_THREADS=%NUMBER_OF_PROCESSORS%

:: 2. AKTYWACJA SRODOWISKA VENV
if exist "venv\Scripts\activate.bat" (
    echo [OK] Aktywacja venv...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [OK] Aktywacja .venv...
    call .venv\Scripts\activate.bat
) else (
    echo [INFO] Uzywanie systemowej instalacji Pythona.
)

:: 3. AUTO-INSTALACJA WYMAGANYCH MODULOW
echo.
echo [1/2] Weryfikacja i instalacja pakietow pip...
python -m pip install --upgrade pip --disable-pip-version-check
python -m pip install gradio fastapi uvicorn pandas numpy requests pywavelets scipy openmeteo-requests

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Nie udalo sie zainstalowac wymaganych pakietow.
    pause
    exit /b 1
)

:: 4. WERYFIKACJA PLIKOW WEJSCIOWYCH
if not exist "gui_app.py" (
    echo [BLAD] Nie znaleziono pliku "%cd%\gui_app.py"
    echo         Sprawdz, czy ten .bat lezy w tym samym folderze co gui_app.py.
    pause
    exit /b 1
)

:: 5. URUCHOMIENIE GUI GRADIO - JEDNO OKNO
:: ZMIENIONE: wczesniej ten skrypt dodatkowo odpalal "start ... cmd /k
:: python -m uvicorn api.main:app ..." w OSOBNYM oknie konsoli - gui_app.py
:: w ogole sie do tego API nie odwoluje (potwierdzone w kodzie - GUI
:: pobiera dane bezposrednio z Open-Meteo), wiec to okno bylo zbednym
:: baalastem dla kogos, kto chce tylko GUI. Uzytkownik poprosil o
:: uruchamianie jednym oknem, tak jak analizator-gieldowy-v3/run.bat.
:: Przegladarka otwiera sie juz sama (gui_app.py: app.launch(...,
:: inbrowser=True)) - nie trzeba tego robic tutaj. Kto potrzebuje osobno
:: dzialajacego API/Swagger (http://127.0.0.1:8000/docs), uruchamia
:: run_api.bat.
echo.
echo [2/2] Uruchamianie GUI Gradio...
echo Przegladarka otworzy sie sama za chwile (http://127.0.0.1:7860)
echo.

python gui_app.py

echo.
echo ============================================================
echo GUI zostalo zamkniete.
echo ============================================================
pause
