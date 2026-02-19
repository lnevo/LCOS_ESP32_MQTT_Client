param(
    [switch]$VerboseOutput
)

$ComPort = 'COM3'
$Baud    = 115200
$Broker  = '192.168.137.1'
$MosPub  = 'C:\Program Files\Mosquitto\mosquitto_pub.exe'

if (-not (Test-Path -LiteralPath $MosPub)) {
    Write-Host "mosquitto_pub not found at: $MosPub"
    exit 1
}

Write-Host 'Checking MQTT broker connection...'
$null = & $MosPub -h $Broker -t 'track/test' -m 'ping' -q 1 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to connect to MQTT broker at $Broker"
    exit 1
}
Write-Host "Connected to MQTT broker at $Broker"

$sp = New-Object System.IO.Ports.SerialPort $ComPort, $Baud, 'None', 8, 'One'
$sp.NewLine = "`n"
$sp.ReadTimeout = 1000
$sp.Open()

try {
    while ($true) {
        try {
            $line = $sp.ReadLine().TrimEnd("`r", "`n")
            if ([string]::IsNullOrWhiteSpace($line)) { continue }

            $i = $line.IndexOf(' ')
            if ($i -lt 1) { continue }

            $topic = $line.Substring(0, $i)
            if (-not $topic.StartsWith('track')) { continue }

            $payload = $line.Substring($i + 1)
            if ([string]::IsNullOrWhiteSpace($payload)) { continue }

            $null = & $MosPub -h $Broker -t $topic -m $payload -r 2>&1

            if ($VerboseOutput) {
                Write-Host ('TX -> ' + $topic + ' ' + $payload)
            }
        }
        catch {
            # ignore timeouts / transient read errors
        }
    }
}
finally {
    $sp.Close()
}