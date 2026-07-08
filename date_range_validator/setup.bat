@echo off
setlocal enabledelayedexpansion
title Date Range Validator - Setup

echo ================================================================
echo   Date Range Validator - First-Time Setup
echo ================================================================
echo.
echo This will set up everything the app needs, using a private copy
echo of Python stored ONLY inside this folder (nothing is installed
echo system-wide, and this does not touch any Python you may already
echo have). This requires an internet connection and may take several
echo minutes the first time.
echo.
pause

set "HERE=%~dp0"

REM ------------------------------------------------------------------
REM Step 1: Local, private Python (portable "embeddable" distribution)
REM ------------------------------------------------------------------
if exist "%HERE%python_embed\python.exe" (
    echo [1/4] Local Python already present - skipping download.
) else (
    echo [1/4] Downloading Python 3.11 ^(portable copy, local to this folder^)...
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile '%HERE%python-embed.zip' -UseBasicParsing } catch { exit 1 }"
    if not exist "%HERE%python-embed.zip" (
        echo.
        echo ERROR: Could not download Python. Check your internet connection
        echo and try running this script again.
        pause
        exit /b 1
    )

    echo       Extracting...
    powershell -NoProfile -Command "Expand-Archive -Path '%HERE%python-embed.zip' -DestinationPath '%HERE%python_embed' -Force"
    del "%HERE%python-embed.zip"

    REM The embeddable distribution ships with site-packages support
    REM disabled by default; re-enable it so pip-installed packages work.
    powershell -NoProfile -Command "(Get-Content '%HERE%python_embed\python311._pth') -replace '#import site','import site' | Set-Content '%HERE%python_embed\python311._pth'"

    echo       Installing pip...
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%HERE%get-pip.py' -UseBasicParsing } catch { exit 1 }"
    "%HERE%python_embed\python.exe" "%HERE%get-pip.py" --no-warn-script-location
    del "%HERE%get-pip.py"
)

REM ------------------------------------------------------------------
REM Step 2: Python packages
REM ------------------------------------------------------------------
echo.
echo [2/4] Installing required Python packages...
echo       ^(EasyOCR pulls in PyTorch, a large download - this can take
echo       10+ minutes on the first run depending on your connection.^)
"%HERE%python_embed\python.exe" -m pip install --no-warn-script-location -r "%HERE%requirements.txt"
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed. Scroll up to see which
    echo package failed, then try running this script again.
    pause
    exit /b 1
)

REM ------------------------------------------------------------------
REM Step 3: Tesseract OCR (native engine - not a Python package, needs
REM its own installer; this cannot be made fully silent/invisible
REM because it installs into Program Files and Windows will ask you
REM to confirm that).
REM ------------------------------------------------------------------
echo.
where tesseract >nul 2>nul
if %errorlevel%==0 (
    echo [3/4] Tesseract OCR already found on PATH - skipping.
) else if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo [3/4] Tesseract OCR already installed - skipping.
) else (
    echo [3/4] Tesseract OCR ^(the OCR engine itself^) is not installed yet.
    echo       Downloading the official installer from the Tesseract
    echo       project on GitHub...
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe' -OutFile '%HERE%tesseract-setup.exe' -UseBasicParsing } catch { exit 1 }"
    if exist "%HERE%tesseract-setup.exe" (
        echo       Launching the installer - please click through it once
        echo       ^(the default options are fine^). This part needs you.
        start /wait "" "%HERE%tesseract-setup.exe"
        del "%HERE%tesseract-setup.exe"
    ) else (
        echo.
        echo       Could not auto-download the Tesseract installer.
        echo       Please install it manually from:
        echo       https://github.com/UB-Mannheim/tesseract/wiki
        echo       then run this setup script again.
        pause
        exit /b 1
    )
)

echo.
echo [4/4] Setup complete!
echo.
echo You can now double-click run.bat any time to start the application.
echo.
pause
