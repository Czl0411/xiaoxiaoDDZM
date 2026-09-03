$ErrorActionPreference = "Stop"
# 关闭旧服务
$port = 7902
try { $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn -and $conn.OwningProcess -ne 0) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 } } catch {}
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "startup.log"
$Wheelhouse = Join-Path $Root "wheelhouse"
$LocalBrowsers = Join-Path $Root "ms-playwright"
$BundledPython = Join-Path $Root "runtime\python\python.exe"
$env:PLAYWRIGHT_BROWSERS_PATH = $LocalBrowsers
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONUTF8 = "1"

function Write-StartupLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Invoke-LoggedCommand {
  param(
    [string]$FilePath,
    [string[]]$Arguments
  )
  & $FilePath @Arguments 2>&1 | ForEach-Object {
    Add-Content -Path $Log -Value $_.ToString() -Encoding UTF8
  }
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
  }
}

function Test-PythonDeps {
  param([string]$PythonExe)
  & $PythonExe -c "import fastapi, uvicorn, playwright, pydantic; raise SystemExit(0)" *> $null
  return ($LASTEXITCODE -eq 0)
}

try {
  Write-StartupLog "Starting DZMM web bot."

  if (Test-Path $BundledPython) {
    $Python = $BundledPython
    Write-StartupLog "Using bundled Python: $Python"
  } elseif (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-StartupLog "Creating virtual environment."
    try {
      Invoke-LoggedCommand "py" @("-3", "-m", "venv", ".venv")
    } catch {
      Invoke-LoggedCommand "python" @("-m", "venv", ".venv")
    }
  }

  if (-not (Test-Path $BundledPython) -and -not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Failed to create .venv. Please install Python 3.11+."
  }

  if (-not $Python) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    Write-StartupLog "Using virtual environment Python: $Python"
  }
  $ServiceLog = Join-Path $LogDir "service.log"
  $ServiceErrorLog = Join-Path $LogDir "service-error.log"

  if ((Test-Path $BundledPython) -and (Test-PythonDeps $Python)) {
    Write-StartupLog "Bundled Python dependencies are ready. Skipping pip install."
  } else {
    Write-StartupLog "Installing dependencies."
    if (Test-Path $Wheelhouse) {
      Write-StartupLog "Installing dependencies from bundled wheelhouse."
      Invoke-LoggedCommand $Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", "requirements.txt")
    } else {
      Write-StartupLog "Bundled wheelhouse not found. Installing dependencies from network."
      try {
        Invoke-LoggedCommand $Python @("-m", "pip", "install", "-r", "requirements.txt")
      } catch {
        Write-StartupLog "Default pip source failed. Retrying with Tsinghua mirror."
        Invoke-LoggedCommand $Python @("-m", "pip", "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "-r", "requirements.txt")
      }
    }
  }

  if (Test-Path (Join-Path $LocalBrowsers "chromium-1148")) {
    Write-StartupLog "Bundled Playwright Chromium is ready. Skipping browser download."
  } else {
    Write-StartupLog "Installing Playwright Chromium."
    $env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"
    Invoke-LoggedCommand $Python @("-m", "playwright", "install", "chromium")
  }

  Write-StartupLog "Launching service with hidden window."
  $env:DZMM_SKIP_AUTO_OPEN = "1"
  $proc = Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $ServiceLog -RedirectStandardError $ServiceErrorLog

  $ready = $false
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
      Write-StartupLog ("Service exited early with code " + $proc.ExitCode + ". Check service-error.log.")
      break
    }
    try {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:7902/api/status" -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -eq 200) {
        $ready = $true
        break
      }
    } catch {}
  }

  if ($ready) {
    Write-StartupLog "Service is ready. Opening manager page."
    Start-Process "http://127.0.0.1:7902"
  } else {
    Write-StartupLog "Service did not become ready within 30 seconds."
  }
} catch {
  Write-StartupLog ("ERROR: " + $_.Exception.Message)
}
