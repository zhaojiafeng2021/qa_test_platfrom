<#
.SYNOPSIS
    代码用例测试平台 一键启动/停止/状态检查脚本

.DESCRIPTION
    管理服务: MySQL / Redis / MinIO / FastAPI 后端 / Vite 前端 / arq 主 Worker / arq 代码用例 Worker /
             arq 覆盖率 Worker / demo-webapp (JaCoCo tcpserver 演示应用)
    所有长驻服务用 Start-Process 后台启动,日志写到 logs\ 目录,不绑定当前终端。
    端口在下方"端口配置"中统一修改 (默认 MySQL 3306 / Redis 6379 / MinIO 9000 / 后端 8000 / 前端 5274)。

.PARAMETER Action
    start     - 启动所有未运行的服务(已运行的跳过)
    stop      - 停止所有服务(MySQL 为数据库服务,跳过停止)
    status    - 查看所有服务状态
    restart   - 重启所有服务(等于 stop + start)
    logs      - 打开 logs 目录
    start-dev - 开发模式: 后端前台运行,其他服务后台运行

.EXAMPLE
    .\qa-server.ps1 start
    .\qa-server.ps1 status
    .\qa-server.ps1 stop
    .\qa-server.ps1 restart
    .\qa-server.ps1 logs
    .\qa-server.ps1 start-dev
#>

param(
    [Parameter(Position=0)]
    [ValidateSet('start','stop','status','restart','logs','start-dev')]
    [string]$Action = 'status'
)

# ============ 路径配置 ============
$ProjectRoot   = 'C:\Users\gg.zhao\code-case-platform'
$BackendDir    = Join-Path $ProjectRoot 'backend'
$FrontendDir   = Join-Path $ProjectRoot 'frontend'
$VenvPython    = Join-Path $BackendDir 'venv\Scripts\python.exe'
$RedisExe      = 'C:\Users\gg.zhao\redis\Redis-7.4.2-Windows-x64-msys2\redis-server.exe'
$MysqlExe      = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe'
$MysqlDataDir  = 'C:\ProgramData\MySQL\MySQL Server 8.4\data'
$ToolsDir      = 'C:\Users\gg.zhao\tools'
$MinioExe      = Join-Path $ToolsDir 'minio\minio.exe'
$MinioDataDir  = Join-Path $ToolsDir 'minio-data'
$JacocoAgent   = Join-Path $ToolsDir 'jacoco\jacocoagent.jar'
$DemoAppDir    = Join-Path $ToolsDir 'deployments\demo-webapp\demo-webapp'
$DemoDeployPs1 = Join-Path $ToolsDir 'test_java_project\demo-webapp\deploy.ps1'
$LogDir        = Join-Path $ProjectRoot 'logs'

# ============ 端口配置 ============
$BackendPort   = 8000
$FrontendPort  = 5274
$MinioPort     = 9000
$MinioConsole  = 9001
$DemoAppPort   = 18080
$DemoAgentPort = 6300
$PidFile       = Join-Path $LogDir '.uvicorn.pid'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# ============ 服务定义 ============
$Services = @(
    @{ Name='MySQL';               Port=3306; Type='mysql';   Log='mysql.log' },
    @{ Name='Redis';               Port=6379; Type='process'; Exe=$RedisExe; Args=@('--port','6379','--bind','127.0.0.1'); Log='redis.log' },
    @{ Name='MinIO';               Port=$MinioPort; Type='shell';
       Cmd="`$env:MINIO_ROOT_USER='minioadmin'; `$env:MINIO_ROOT_PASSWORD='minioadmin'; & '$MinioExe' server '$MinioDataDir' --address :$MinioPort --console-address :$MinioConsole";
       Check=$MinioExe; WorkDir=$ToolsDir; Log='minio.log' },
    @{ Name='FastAPI 后端';         Port=$BackendPort; Type='python';
       Cmd="uvicorn app.main:app --host 0.0.0.0 --port $BackendPort";
       DevCmd="uvicorn app.main:app --host 0.0.0.0 --port $BackendPort --reload";
       WorkDir=$BackendDir; Log='FastAPI_backend.log' },
    @{ Name='Vite 前端';            Port=$FrontendPort; Type='node';
       Cmd="`$env:VITE_PROXY_TARGET='http://localhost:$BackendPort'; node node_modules/vite/bin/vite.js --port $FrontendPort --strictPort";
       PreCmd='node scripts/load-apollo-env.mjs'; WorkDir=$FrontendDir; Log='Vite_frontend.log' },
    @{ Name='arq 主 Worker';        Port=0;    Type='arq';     Module='app.workers.settings.WorkerSettings'; WorkDir=$BackendDir; Log='arq_main_worker.log' },
    @{ Name='arq CodeCase Worker';  Port=0;    Type='arq';     Module='app.workers.settings.CodeCaseWorkerSettings'; WorkDir=$BackendDir; Log='arq_codecase_worker.log' },
    @{ Name='arq 覆盖率 Worker';    Port=0;    Type='arq';     Module='app.workers.settings.CoverageJavaWorkerSettings'; WorkDir=$BackendDir; Log='arq_coverage_worker.log' },
    @{ Name='demo-webapp';          Port=$DemoAppPort; Type='shell';
       # 已编译则直接带 JaCoCo tcpserver agent 启动; 未编译请先运行 deploy.ps1 (git 拉取 + mvn compile)
       Cmd="& java '-javaagent:$JacocoAgent=output=tcpserver,address=*,port=$DemoAgentPort' -cp '$DemoAppDir\target\classes' com.example.demo.App";
       Env=@{ APP_PORT="$DemoAppPort" };
       Check="$DemoAppDir\target\classes"; CheckHint="请先执行: & '$DemoDeployPs1'";
       WorkDir=$DemoAppDir; Log='demo_webapp.log' }
)

# ============ 工具函数 ============
function Get-PortListening($port) {
    if ($port -eq 0) { return $null }
    return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-ServiceLogFile($svc) {
    $name = if ($svc.Log) { $svc.Log } else { "$($svc.Name -replace '\s','_').log" }
    return Join-Path $LogDir $name
}

function Get-ArqProcesses($module) {
    return Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*arq* $module*" }
}

function Write-Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [ERR]  $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }

function Stop-ServiceByName($svc) {
    switch ($svc.Type) {
        'mysql' {
            Write-Info "$($svc.Name) 为数据库服务,跳过停止 (如需停止请用 mysqladmin shutdown 或服务管理)"
        }
        'process' {
            $procs = Get-Process -Name (Split-Path $svc.Exe -Leaf).Replace('.exe','') -ErrorAction SilentlyContinue
            if ($procs) {
                $procs | Stop-Process -Force -ErrorAction SilentlyContinue
                Write-Ok "$($svc.Name) 已停止 (PID $($procs.Id -join ','))"
            }
        }
        'python' {
            # uvicorn 在 Windows 上有 reloader/spawn 两层且 PID 有时会从用户态枚举中"消失",
            # stop 时按 pid 文件优先杀, 再按端口, 最后兜底杀所有 venv 下 python.exe
            $killed = @()

            # 1) pid 文件优先
            if (Test-Path $PidFile) {
                $pids = (Get-Content $PidFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\d+$' }) |
                    ForEach-Object { [int]$_ }
                foreach ($p in $pids) {
                    & taskkill /F /T /PID $p 2>&1 | Out-Null
                    $killed += $p
                }
            }

            # 2) 端口兜底 (连试两次, 应对瞬时抖动)
            foreach ($attempt in 1..2) {
                $conn = Get-PortListening $svc.Port
                if ($conn) {
                    & taskkill /F /T /PID $conn.OwningProcess 2>&1 | Out-Null
                    $killed += $conn.OwningProcess
                }
                Start-Sleep -Milliseconds 500
            }

            # 3) 终极兜底: 杀所有本项目 venv 下的 python.exe (uvicorn + arq 会被一起杀掉,
            #    但 Stop-All 里 arq 已经先停过一遍了, 这里只是清理残留)
            $venvDir = Split-Path (Split-Path $VenvPython -Parent) -Parent
            $venvEscaped = $venvDir.Replace('\','\\')
            $leftovers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "*$venvEscaped*" }
            foreach ($p in $leftovers) {
                & taskkill /F /T /PID $p.ProcessId 2>&1 | Out-Null
                $killed += $p.ProcessId
            }

            $killed = $killed | Select-Object -Unique
            if ($killed.Count) { Write-Ok "$($svc.Name) 已停止 (PID $($killed -join ','))" }
            else { Write-Warn "$($svc.Name) 未运行" }
            if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        }
        { $_ -in 'node','shell' } {
            $conn = Get-PortListening $svc.Port
            if ($conn) {
                & taskkill /F /T /PID $conn.OwningProcess 2>&1 | Out-Null
                Write-Ok "$($svc.Name) 已停止 (PID $($conn.OwningProcess))"
            }
        }
        'arq' {
            foreach ($p in (Get-ArqProcesses $svc.Module)) {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Ok "$($svc.Name) 已停止 (PID $($p.ProcessId))"
            }
        }
    }
}

function Start-ServiceByName($svc, [switch]$ForegroundBackend) {
    $logFile = Get-ServiceLogFile $svc

    if ($svc.Port -gt 0) {
        $conn = Get-PortListening $svc.Port
        if ($conn) {
            Write-Warn "$($svc.Name) 端口 $($svc.Port) 已被 PID $($conn.OwningProcess) 监听, 视为已运行, 跳过 (需重启请用 restart)"
            return
        }
    } elseif ($svc.Type -eq 'arq') {
        $running = Get-ArqProcesses $svc.Module
        if ($running) {
            Write-Warn "$($svc.Name) 已在运行 (PID $($running.ProcessId)),跳过"
            return
        }
    }

    switch ($svc.Type) {
        'mysql' {
            if (Test-Path $MysqlExe) {
                Start-Process -FilePath $MysqlExe -ArgumentList "--datadir=`"$MysqlDataDir`"" -WindowStyle Minimized
                Write-Ok "$($svc.Name) 启动中..."
            } else {
                Write-Err "$($svc.Name) 可执行文件不存在: $MysqlExe"
            }
        }
        'process' {
            if (Test-Path $svc.Exe) {
                Start-Process -FilePath $svc.Exe -ArgumentList $svc.Args -WindowStyle Minimized
                Write-Ok "$($svc.Name) 启动中..."
            } else {
                Write-Err "$($svc.Name) 可执行文件不存在: $($svc.Exe)"
            }
        }
        'python' {
            # 开发模式: 后端在当前终端前台运行, 带 --reload 热重载
            if ($ForegroundBackend -and $svc.Name -eq 'FastAPI 后端') {
                Write-Host ""
                Write-Host "==================== 开发模式: 后端前台运行 ====================" -ForegroundColor Cyan
                Write-Host "  后端将在当前终端运行, 可实时查看日志 (--reload 热重载启用)"
                Write-Host "  按 Ctrl+C 停止后端服务"
                Write-Host "  日志同时保存到: $logFile"
                Write-Host "================================================================" -ForegroundColor Cyan
                Write-Host ""

                Push-Location $svc.WorkDir
                try {
                    $env:PYTHONUTF8 = '1'
                    Invoke-Expression "& '$VenvPython' -m $($svc.DevCmd) 2>&1 | Tee-Object -FilePath '$logFile'"
                } finally {
                    Pop-Location
                }
                return
            }

            # 正常模式: 后台运行, 不带 --reload (避免 uvicorn --reload 守护子进程导致 stop 不可靠)
            $cmd = "`$env:PYTHONUTF8=1; & '$VenvPython' -m $($svc.Cmd)"
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WorkingDirectory $svc.WorkDir -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) 启动中... 日志: $logFile"

            # 等待 uvicorn 监听端口后记录 PID
            Start-Sleep -Seconds 2
            $post = Get-PortListening $svc.Port
            if ($post) { $post.OwningProcess | Out-File -FilePath $PidFile -Encoding ascii -Force }
        }
        'node' {
            $cmd = if ($svc.PreCmd) { "$($svc.PreCmd); $($svc.Cmd)" } else { $svc.Cmd }
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WorkingDirectory $svc.WorkDir -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) 启动中... 日志: $logFile"
        }
        'shell' {
            if ($svc.Check -and -not (Test-Path $svc.Check)) {
                Write-Err "$($svc.Name) 依赖不存在: $($svc.Check)"
                if ($svc.CheckHint) { Write-Info $svc.CheckHint }
                return
            }
            $envPrefix = ''
            if ($svc.Env) { foreach ($k in $svc.Env.Keys) { $envPrefix += "`$env:$k='$($svc.Env[$k])'; " } }
            $cmd = "$envPrefix$($svc.Cmd)"
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WorkingDirectory $svc.WorkDir -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) 启动中... 日志: $logFile"
        }
        'arq' {
            $cmd = "`$env:PYTHONUTF8=1; & '$VenvPython' -m arq $($svc.Module)"
            Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-Command',$cmd -WorkingDirectory $svc.WorkDir -WindowStyle Minimized -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
            Write-Ok "$($svc.Name) 启动中... 日志: $logFile"
        }
    }
}

function Show-Status {
    Write-Host ""
    Write-Host "============================ 代码用例测试平台 服务状态 ============================" -ForegroundColor Cyan
    Write-Host ""

    foreach ($svc in $Services) {
        $status = '未运行'
        $detail = ''
        if ($svc.Port -gt 0) {
            $conn = Get-PortListening $svc.Port
            if ($conn) {
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
                $status = '运行中'
                $detail = "PID $($conn.OwningProcess) ($($proc.ProcessName))"
            }
        } elseif ($svc.Type -eq 'arq') {
            $running = Get-ArqProcesses $svc.Module
            if ($running) {
                $status = '运行中'
                $detail = "PID $($running.ProcessId -join ',')"
            }
        }
        $line = "  {0,-22} 端口:{1,-6} {2}  {3}" -f $svc.Name, $(if($svc.Port -gt 0){$svc.Port}else{'-'}), $status, $detail
        if ($status -eq '运行中') { Write-Host $line -ForegroundColor Green } else { Write-Host $line -ForegroundColor DarkGray }
    }

    Write-Host ""
    Write-Host "-------------------------------- 健康检查 --------------------------------" -ForegroundColor Cyan

    $redisConn = Get-PortListening 6379
    if ($redisConn) { Write-Ok "Redis 端口 6379 可达 (PID $($redisConn.OwningProcess))" }
    else { Write-Err "Redis 端口 6379 不可达" }

    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$BackendPort/health/live" -UseBasicParsing -TimeoutSec 5
        Write-Ok "后端存活 (/health/live) -> HTTP $($resp.StatusCode)"
    } catch {
        Write-Err "后端存活检查失败: $($_.Exception.Message)"
    }

    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$BackendPort/health/ready" -UseBasicParsing -TimeoutSec 10
        Write-Ok "后端就绪 (/health/ready) -> $($resp.Content)"
    } catch {
        Write-Warn "后端就绪检查超时或失败(依赖 MySQL/Redis,可能未完全启动): $($_.Exception.Message)"
    }

    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$FrontendPort/" -UseBasicParsing -TimeoutSec 5
        Write-Ok "前端 HTTP $($resp.StatusCode)"
    } catch {
        Write-Err "前端访问失败: $($_.Exception.Message)"
    }

    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$MinioPort/minio/health/live" -UseBasicParsing -TimeoutSec 5
        Write-Ok "MinIO 存活 -> HTTP $($resp.StatusCode)"
    } catch {
        Write-Err "MinIO 存活检查失败 (覆盖率产物上传依赖它): $($_.Exception.Message)"
    }

    if (Get-PortListening $DemoAgentPort) { Write-Ok "demo-webapp JaCoCo agent 端口 $DemoAgentPort 可达" }
    else { Write-Warn "demo-webapp JaCoCo agent 端口 $DemoAgentPort 不可达 (runtime 采集会失败)" }

    Write-Info "arq 队列状态详见后端 /health/ready 返回中的 redis/database 字段"
    Write-Info "日志目录: $LogDir"

    Write-Host ""
    Write-Host "===================================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-AccessUrls {
    Write-Host "访问地址:" -ForegroundColor Cyan
    Write-Host "  平台:        http://localhost:$FrontendPort/"
    Write-Host "  MinIO 控制台: http://localhost:$MinioConsole/ (minioadmin/minioadmin)"
    Write-Host "  demo-webapp: http://localhost:$DemoAppPort/  (JaCoCo agent: localhost:$DemoAgentPort)"
    $lanIp = $null
    try {
        $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -in @('Dhcp','Manual') } |
            Select-Object -First 1).IPAddress
    } catch { $lanIp = $null }
    if ($lanIp) { Write-Host "  局域网:      http://${lanIp}:$FrontendPort/" }
}

function Start-All {
    Write-Host ""
    Write-Host "==================== 启动所有服务 ====================" -ForegroundColor Cyan
    foreach ($svc in $Services) { Start-ServiceByName $svc }
    Write-Host ""
    Write-Info "等待服务就绪(10秒)..."
    Start-Sleep -Seconds 10
    Show-Status
    Show-AccessUrls
}

function Stop-All {
    Write-Host ""
    Write-Host "==================== 停止所有服务 ====================" -ForegroundColor Cyan
    # 逆序停止: 先停 Worker/前端/后端, 后停 Redis/MySQL
    $reversed = @(for ($i = $Services.Count - 1; $i -ge 0; $i--) { $Services[$i] })
    foreach ($svc in $reversed) { Stop-ServiceByName $svc }

    # 兜底: 强制杀掉所有本项目 venv 下的 python.exe (uvicorn --reload 有时会脱离枚举, 导致 taskkill 杀不干净)
    $venvDir = Split-Path (Split-Path $VenvPython -Parent) -Parent
    $venvPythons = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "*$($venvDir.Replace('\','\\'))*" }
    foreach ($p in $venvPythons) {
        & taskkill /F /T /PID $p.ProcessId 2>&1 | Out-Null
    }
    if ($venvPythons) { Write-Info "兜底清理: 杀掉本项目 venv 下残留的 $($venvPythons.Count) 个 python.exe 进程" }
    Start-Sleep -Seconds 2

    Write-Host ""
    Show-Status
}

function Start-Dev {
    Write-Host ""
    Write-Host "==================== 开发模式启动 ====================" -ForegroundColor Cyan
    Write-Host "  后端将在前台运行, 可实时查看日志"
    Write-Host "  其他服务 (MySQL/Redis/前端/arq Worker) 将在后台运行"
    Write-Host "======================================================" -ForegroundColor Cyan
    Write-Host ""

    # 先启动其他服务(后台)
    foreach ($svc in $Services) {
        if ($svc.Name -ne 'FastAPI 后端') { Start-ServiceByName $svc }
    }

    Write-Host ""
    Write-Info "等待依赖服务就绪 (6s) ..."
    Start-Sleep -Seconds 6
    Write-Host ""

    # 最后在前台启动后端
    $backendSvc = $Services | Where-Object { $_.Name -eq 'FastAPI 后端' } | Select-Object -First 1
    if ($backendSvc) { Start-ServiceByName $backendSvc -ForegroundBackend }

    # 后端退出(Ctrl+C)后
    Write-Host ""
    Write-Host "==================== 后端已停止 ====================" -ForegroundColor Yellow
    Write-Host "  其他服务仍在后台运行"
    Write-Host "  查看状态: .\qa-server.ps1 status"
    Write-Host "  停止所有: .\qa-server.ps1 stop"
    Write-Host "====================================================" -ForegroundColor Yellow
    Write-Host ""
}

switch ($Action) {
    'start'     { Start-All }
    'stop'      { Stop-All }
    'status'    { Show-Status }
    'restart'   { Stop-All; Start-Sleep -Seconds 2; Start-All }
    'start-dev' { Start-Dev }
    'logs'      {
        if (Test-Path $LogDir) { explorer.exe $LogDir } else { Write-Err "logs 目录不存在: $LogDir" }
    }
}
