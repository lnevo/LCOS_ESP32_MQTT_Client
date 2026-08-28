Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\.py') } |
  ForEach-Object {
    Write-Output "killing PID=$($_.ProcessId) $($_.CommandLine)"
    Stop-Process -Id $_.ProcessId -Force
  }
Start-Sleep -Seconds 1
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'serial_to_mqtt\.py') })
if ($left.Count -eq 0) { 'no serial_to_mqtt running' } else { $left | ForEach-Object { "still PID=$($_.ProcessId)" } }
