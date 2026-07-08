@echo off
title Date Range Validator

set "HERE=%~dp0"

if not exist "%HERE%python_embed\python.exe" (
    echo It looks like setup hasn't been run yet.
    echo Please double-click setup.bat first ^(one-time step^), then
    echo come back and run this again.
    pause
    exit /b 1
)

"%HERE%python_embed\python.exe" "%HERE%main.py"

if errorlevel 1 (
    echo.
    echo The application closed with an error - see the details above.
    pause
)
