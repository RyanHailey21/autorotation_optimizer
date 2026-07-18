param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$windowsRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$url = "http://127.0.0.1:$Port/"
$arguments = @(
    "--cd", $windowsRoot,
    "bash", "./run_app.sh", "--no-open", "--port", $Port
)

$process = Start-Process -FilePath "wsl.exe" -ArgumentList $arguments -PassThru -NoNewWindow
try {
    if (-not $NoOpen) {
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            try {
                Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 1 | Out-Null
                Start-Process $url
                break
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
    }
    Wait-Process -Id $process.Id
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id
    }
}
