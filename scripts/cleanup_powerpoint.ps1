param([Parameter(Mandatory=$true)][string]$Marker)
$ErrorActionPreference = 'Stop'
$record = Get-Content -LiteralPath $Marker -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.Owned -eq $true) {
    $ownedProcess = Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue
    if ($ownedProcess -and $ownedProcess.ProcessName -eq 'POWERPNT' -and
        $ownedProcess.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.StartTicks) {
        Stop-Process -Id $ownedProcess.Id -Force
    }
}
