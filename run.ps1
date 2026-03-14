$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectRoot "main.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "未找到虚拟环境解释器: $PythonExe"
}

if (-not (Test-Path $MainScript)) {
    Write-Error "未找到主程序: $MainScript"
}

& $PythonExe $MainScript @args
