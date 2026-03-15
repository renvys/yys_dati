@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=C:\Users\renvy\AppData\Local\Programs\Python\Python312\python.exe"
set "SPEC_FILE=%PROJECT_ROOT%yys_dati.spec"

if not exist "%PYTHON_EXE%" (
    echo Python not found: "%PYTHON_EXE%"
    exit /b 1
)

if not exist "%SPEC_FILE%" (
    echo Spec file not found: "%SPEC_FILE%"
    exit /b 1
)

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
