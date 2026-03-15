$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "C:\Users\renvy\AppData\Local\Programs\Python\Python312\python.exe"
$SpecFile = Join-Path $ProjectRoot "yys_dati.spec"

if (-not (Test-Path $PythonExe)) {
    throw "Python not found: $PythonExe"
}

if (-not (Test-Path $SpecFile)) {
    throw "Spec file not found: $SpecFile"
}

& $PythonExe -m PyInstaller --noconfirm --clean $SpecFile
