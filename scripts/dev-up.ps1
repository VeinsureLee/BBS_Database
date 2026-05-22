# Start Neo4j (in a new window if not already up) and run npm run visualize.
# After visualize returns, Neo4j stays up so you can keep using the Browser.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1
#         OR add an npm script:  "dev:up": "powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1"

$ErrorActionPreference = 'Stop'

# Edit if you installed Neo4j elsewhere.
$Neo4jBat = 'D:\Neo4j\neo4j-community-2025.12.1\bin\neo4j.bat'
$BoltHost = 'localhost'
$BoltPort = 7687
$MaxWaitSeconds = 90

if (-not (Test-Path $Neo4jBat)) {
    Write-Error "Neo4j not found at $Neo4jBat. Edit \$Neo4jBat in this script."
    exit 1
}

function Test-BoltUp {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($BoltHost, $BoltPort, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(500)
        if ($ok -and $client.Connected) { $client.Close(); return $true }
        $client.Close(); return $false
    } catch { return $false }
}

if (Test-BoltUp) {
    Write-Host "[dev-up] Neo4j already listening on ${BoltHost}:${BoltPort}, reusing it."
} else {
    Write-Host "[dev-up] Starting Neo4j in a new window (will stay open after this script ends)..."
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Write-Host 'Neo4j console (do not close; Ctrl+C to stop)'; & `"$Neo4jBat`" console"
    ) | Out-Null

    Write-Host -NoNewline "[dev-up] Waiting for Bolt"
    $elapsed = 0
    while (-not (Test-BoltUp)) {
        if ($elapsed -ge $MaxWaitSeconds) {
            Write-Host ""
            Write-Error "Bolt did not come up within $MaxWaitSeconds s. Check the Neo4j window for errors."
            exit 1
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    Write-Host " ready (${elapsed}s)."
}

# Move to repo root (this script lives in scripts/)
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[dev-up] Running npm run visualize"
npm run visualize
