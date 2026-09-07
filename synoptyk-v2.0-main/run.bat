@echo off
title Synoptyk-v2.0 -- TIMDR Full Performance Mode
color 0A
cls

cd /d "%~dp0"

echo ============================================================
echo   SYNOPTYK-v2.0: Uruchamianie GUI (jedno okno)
echo   Katalog roboczy: %cd%
echo ============================================================
echo.

set PYTHONUNBUFFERED=1
set OMP_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set MKL_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set OPENBLAS_NUM_THREADS=%NUMBER_OF_PROCESSORS%
set VECLIB_MAXIMUM_THREADS=%NUMBER_OF_PROCESSORS%
set NUMEXPR_NUM_THREADS=%NUMBER_OF_PROCESSORS%

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
echo [1/2] Instalacja pakietow pip...
python -m pip install --upgrade pip --disable-pip-version-check
python -m pip install gradio fastapi uvicorn pandas numpy requests pywavelets scipy openmeteo-requests

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Instalacja pakietow nie powiodla sie.
    pause
    exit /b 1
)

if not exist "gui_app.py" (
    echo [BLAD] Nie znaleziono pliku gui_app.py
    pause
    exit /b 1
)

echo.
echo [2/2] Uruchamianie GUI...
echo.
echo (NAPRAWIONE: szukanie wolnego portu robi teraz sam gui_app.py w
echo  Pythonie - poprzednia wersja tego pliku .bat probowala to zrobic
echo  petla z "python - ^<^<EOF", czyli skladnia heredoc z basha/Linuxa,
echo  ktorej Windows cmd.exe NIE obsluguje. To najprawdopodobniej byla
echo  przyczyna zamykajacego sie okienka konsoli - blad parsowania .bat
echo  zanim gui_app.py w ogole zdazyl sie uruchomic.)
echo.

python gui_app.py

echo.
echo ============================================================
echo GUI zostalo zamkniete.
echo ============================================================
pause
