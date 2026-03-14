@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "MAIN_SCRIPT=%PROJECT_ROOT%main.py"

if not exist "%PYTHON_EXE%" (
    echo Virtualenv interpreter not found: "%PYTHON_EXE%"
    exit /b 1
)

if not exist "%MAIN_SCRIPT%" (
    echo Main script not found: "%MAIN_SCRIPT%"
    exit /b 1
)

"%PYTHON_EXE%" "%MAIN_SCRIPT%" %*
