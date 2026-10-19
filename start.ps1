<#
.SYNOPSIS
    Code Case Platform launcher (start / stop / status / restart)

.DESCRIPTION
    Manages 6 services: MySQL / Redis / FastAPI backend / Vite frontend /
    arq main worker / arq code-case worker.
    Long-running services are started in the background; logs go to logs\.

.PARAMETER Action
    start   - start services that are not running yet (skip running ones)
    stop    - stop all services
    status  - show service status
    restart - stop then start

.EXAMPLE
    .\start.ps1 start
    .\start.ps1 status
    .\start.ps1 stop
#>

param(
    [Parameter(Position=0)]
    [ValidateSet('start','stop','status','restart')]
    [string]$Action = 'status'
)

# ============ Paths ============
$ProjectRoot  = 'C:\Users\gg.zhao\code-case-platform'
$BackendDir   = Join-Path $ProjectRoot 'backend'
$FrontendDir  = Join-Path $ProjectRoot 'frontend'
$VenvPython   = Join-Path $BackendDir 'venv\Scripts\python.exe'
$RedisExe     = 'C:\Users\gg.zhao\redis\Redis-7.4.2-Windows-x64-msys2\redis-server.exe'
$MysqlExe     = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe'
$MysqlDataDir = 'C:\ProgramData\MySQL\MySQL Server 8.4\data'
$LogDir       = Join-Path $ProjectRoot 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# ============ Services ============
$Services = @(
    @{ Name='MySQL';               Port=3306; Type='mysql' },
    @{ Name='Redis';               Port=6379; Type='redis' },
    @{ Name='FastAPI backend';     Port=8100; Type='python'; Cmd='uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload'; WorkDir=$BackendDir },
    @{ Name='Vite frontend';       Port=5273; Type='node';   Cmd='node node_modules/vite/bin/vite.js'; WorkDir=$FrontendDir },
    @{ Name='arq main worker';     Port=0;    Type='arq';    Module='app.workers.settings.WorkerSettings'; WorkDir=$BackendDir },
    @{ Name='arq codecase worker'; Port=0;    Type='arq';    Module='app.workers.settings.CodeCaseWorkerSettings'; WorkDir=$BackendDir }
)

# ============ Helpers ============
function Get-PortListening($port) {
    if ($port -eq 0) { return $null }
    return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}
function Write-Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [ERR]  $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }

function Get-ArqProcess($module) {
    return Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*arq* $module*" }
}

function Start-ArqWorker($svc) {
    $running = Get-ArqProcess $svc.Module
    if ($running) { Write-Warn "$($svc.Name) already running (PID $($running.ProcessId)), skip"; return }
    $logFile = Join-Path $LogDir "$($svc.Name -replace '\s','_').log"
    $cmd = "`$env:PYTHONUTF8=1; Set-Location '$($svc.WorkDir)'; & '$VenvPython' -m arq $($svc.Module)"
    Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
    Write-Ok "$($svc.Name) starting... log: $logFile"
}

function Start-ServiceByName($svc) {
    $logFile = Join-Path $LogDir "$($svc.Name -replace '\s','_').log"

    if ($svc.Port -gt 0) {
        $conn = Get-PortListening $svc.Port
        if ($conn) { Write-Warn "$($svc.Name) already running (PID $($conn.OwningProcess)), skip"; return }
    }

    switch ($svc.Type) {
        'mysql' {
            Start-Process -FilePath $MysqlExe -ArgumentList "--datadir=`"$MysqlDataDir`"" -WindowStyle Minimized
            Write-Ok "$($svc.Name) starting..."
        }
        'redis' {
            Start-Process -FilePath $RedisExe -ArgumentList '--port','6379','--bind','127.0.0.1' -WindowStyle Minimized
            Write-Ok "$($svc.Name) starting..."
        }
        'python' {
            $cmd = "`$env:PYTHONUTF8=1; Set-Location '$($svc.WorkDir)'; & '$VenvPython' -m $($svc.Cmd)"
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) starting... log: $logFile"
        }
        'node' {
            $cmd = "Set-Location '$($svc.WorkDir)'; $($svc.Cmd)"
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) starting... log: $logFile"
        }
        'arq' { Start-ArqWorker $svc }
    }
}

function Stop-ServiceByName($svc) {
    switch ($svc.Type) {
        'mysql' {
            $conn = Get-PortListening $svc.Port
            if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Ok "$($svc.Name) stopped" }
            else { Write-Warn "$($svc.Name) not running" }
        }
        'redis' {
            $procs = Get-Process redis-server -ErrorAction SilentlyContinue
            if ($procs) { $procs | Stop-Process -Force -ErrorAction SilentlyContinue; Write-Ok "$($svc.Name) stopped (PID $($procs.Id -join ','))" }
            else { Write-Warn "$($svc.Name) not running" }
        }
        'python' {
            $conn = Get-PortListening $svc.Port
            if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Ok "$($svc.Name) stopped (PID $($conn.OwningProcess))" }
            else { Write-Warn "$($svc.Name) not running" }
        }
        'node' {
            $conn = Get-PortListening $svc.Port
            if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Ok "$($svc.Name) stopped (PID $($conn.OwningProcess))" }
            else { Write-Warn "$($svc.Name) not running" }
        }
        'arq' {
            $procs = Get-ArqProcess $svc.Module
            if ($procs) {
                foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; Write-Ok "$($svc.Name) stopped (PID $($p.ProcessId))" }
            } else { Write-Warn "$($svc.Name) not running" }
        }
    }
}

function Show-Status {
    Write-Host ""
    Write-Host "============ Code Case Platform service status ============" -ForegroundColor Cyan
    foreach ($svc in $Services) {
        $status = 'DOWN'; $detail = ''
        if ($svc.Port -gt 0) {
            $conn = Get-PortListening $svc.Port
            if ($conn) { $status = 'UP  '; $detail = "PID $($conn.OwningProcess)" }
        } else {
            $running = Get-ArqProcess $svc.Module
            if ($running) { $status = 'UP  '; $detail = "PID $($running.ProcessId)" }
        }
        $line = "  {0,-20} port:{1,-6} {2} {3}" -f $svc.Name, $(if($svc.Port -gt 0){$svc.Port}else{'-'}), $status, $detail
        Write-Host $line
    }
    Write-Host ""
    Write-Host "---------------- health check ----------------" -ForegroundColor Cyan
    try { $resp = Invoke-WebRequest 'http://127.0.0.1:8100/health/ready' -UseBasicParsing -TimeoutSec 10; Write-Ok "backend ready -> $($resp.Content)" }
    catch { Write-Warn "backend ready check failed: $($_.Exception.Message)" }
    try { $resp = Invoke-WebRequest 'http://127.0.0.1:5273/' -UseBasicParsing -TimeoutSec 5; Write-Ok "frontend HTTP $($resp.StatusCode)" }
    catch { Write-Err "frontend unreachable: $($_.Exception.Message)" }
    Write-Host ""
    Write-Host "  URL: http://localhost:5273/" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Start-All {
    Write-Host ""
    Write-Host "==================== start all services ====================" -ForegroundColor Cyan
    foreach ($svc in $Services) { Start-ServiceByName $svc }
    Write-Info "waiting for services (10s)..."
    Start-Sleep -Seconds 10
    Show-Status
}

function Stop-All {
    Write-Host ""
    Write-Host "==================== stop all services ====================" -ForegroundColor Cyan
    $reversed = @($Services | Select-Object -Reverse)
    foreach ($svc in $reversed) { Stop-ServiceByName $svc }
    Write-Host ""
    Show-Status
}

switch ($Action) {
    'start'   { Start-All }
    'stop'    { Stop-All }
    'status'  { Show-Status }
    'restart' { Stop-All; Start-Sleep -Seconds 2; Start-All }
}
