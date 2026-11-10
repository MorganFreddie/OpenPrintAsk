param(
    [ValidateSet("auto", "live", "replay")]
    [string]$Mode = "auto",
    [int]$Port = 8765,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Host "[提示] 没有 .env；auto 模式下无凭证会落到 replay。" -ForegroundColor Yellow
}

$serverArgs = @("server.py", "--mode", $Mode, "--port", "$Port")
if ($Open) { $serverArgs += "--open" }

Write-Host "[启动] python $($serverArgs -join ' ')" -ForegroundColor Cyan
python @serverArgs
