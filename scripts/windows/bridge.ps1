<#
  bridge.ps1 - control the background serial<->MQTT bridge.

    bridge start     start it (no-op if already running)
    bridge stop      stop it (runner + serial_to_mqtt.py)
    bridge restart   stop, then start
    bridge status    show PIDs and the last log lines
    bridge log       follow logs\bridge.log (like tail -f; Ctrl+C stops the tail, not the bridge)
    bridge install   register the LcosBridge task (starts at boot, no login needed). Run elevated.
    bridge uninstall remove the task

  The bridge runs via scripts\windows\bridge_runner.py, which timestamps output into
  logs\bridge.log and restarts the bridge if it exits.
#>
param([Parameter(Position = 0)][string]$Cmd = 'status', [int]$Lines = 50)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Runner = Join-Path $PSScriptRoot 'bridge_runner.py'
$Log    = Join-Path $Root 'logs\bridge.log'
$Task   = 'LcosBridge'

function Get-Python {
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) { if (Test-Path $p) { return $p } }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    throw 'python.exe not found'
}

function Get-BridgeProcs {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='py.exe'" |
        Where-Object { $_.CommandLine -match 'bridge_runner\.py|serial_to_mqtt\.py' })
}

function Show-Status {
    $p = Get-BridgeProcs
    if ($p.Count -eq 0) { 'bridge: STOPPED' }
    else {
        'bridge: RUNNING'
        $p | ForEach-Object {
            $kind = if ($_.CommandLine -match 'bridge_runner') { 'runner' } else { 'bridge' }
            "  {0,-6} pid {1,-6} since {2}" -f $kind, $_.ProcessId, $_.CreationDate
        }
        if (-not ($p | Where-Object CommandLine -match 'bridge_runner')) {
            '  (no runner: this is a foreground/manual bridge, not the background one)'
        }
    }
    $t = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    if ($t) { "task $Task`: $($t.State)" } else { "task $Task`: not installed" }
    if (Test-Path $Log) { "--- $Log (last 10)"; Get-Content $Log -Tail 10 -Encoding UTF8 }
}

function Start-Bridge {
    if ((Get-BridgeProcs).Count -gt 0) { 'already running'; Show-Status; return }
    $started = $false
    if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) {
        try { Start-ScheduledTask -TaskName $Task; $started = $true } catch { "task start failed ($_); starting directly" }
    }
    if (-not $started) {
        Start-Process -FilePath (Get-Python) -ArgumentList @('-u', "`"$Runner`"") -WorkingDirectory $Root -WindowStyle Hidden
    }
    Start-Sleep -Seconds 4
    Show-Status
}

function Stop-Bridge {
    $t = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    if ($t -and $t.State -eq 'Running') { try { Stop-ScheduledTask -TaskName $Task } catch {} }
    # runner first, so it can't restart the bridge
    foreach ($pat in 'bridge_runner\.py', 'serial_to_mqtt\.py') {
        Get-BridgeProcs | Where-Object CommandLine -match $pat | ForEach-Object {
            "stopping pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
    if ((Get-BridgeProcs).Count -eq 0) {
        'bridge: STOPPED'
        if (Test-Path $Log) { Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss} [runner] stopped by 'bridge stop'" -f (Get-Date)) -Encoding UTF8 }
    } else { 'WARNING: still running'; Show-Status }
}

function Follow-Log {
    if (-not (Test-Path $Log)) { New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null; New-Item -ItemType File $Log | Out-Null }
    $Host.UI.RawUI.WindowTitle = 'Bridge log'
    "following $Log  (Ctrl+C stops the tail; the bridge keeps running)"
    Get-Content -Path $Log -Tail $Lines -Wait -Encoding UTF8
}

function Install-Task {
    $py = Get-Python
    $action  = New-ScheduledTaskAction -Execute $py -Argument "-u `"$Runner`"" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT30S'   # let the network and the Nano's COM port come up
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
    # No Task Scheduler restart-on-failure: bridge_runner.py restarts the bridge itself,
    # and a scheduler restart would undo 'bridge stop'.
    Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'LCOS serial<->MQTT bridge (scripts\windows\bridge.ps1). Log: logs\bridge.log' -Force | Out-Null
    "task $Task installed (at boot +30 s, runs without login)"
}

switch ($Cmd.ToLower()) {
    'start'     { Start-Bridge }
    'stop'      { Stop-Bridge }
    'restart'   { Stop-Bridge; Start-Bridge }
    'status'    { Show-Status }
    'log'       { Follow-Log }
    'tail'      { Follow-Log }
    'install'   { Install-Task }
    'uninstall' { Unregister-ScheduledTask -TaskName $Task -Confirm:$false; "task $Task removed" }
    default     { Get-Help $PSCommandPath -Detailed | Out-String | Write-Output; exit 2 }
}
