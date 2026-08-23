$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$mutex = [System.Threading.Mutex]::new($false, 'GEOGitHubSync')
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    $stampFile = Join-Path $root '.sync-github.lock'
    if (Test-Path $stampFile) {
        $last = [datetime]::Parse((Get-Content $stampFile -Raw).Trim())
        if (((Get-Date) - $last).TotalSeconds -lt 20) { exit 0 }
    }

    git rev-parse --is-inside-work-tree 2>$null | Out-Null
    $status = git status --porcelain
    if (-not $status) { exit 0 }

    git add -A
    $msg = "sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    git -c user.name='x1162697800-web' -c user.email='252107460+x1162697800-web@users.noreply.github.com' commit -m $msg | Out-Null

    git push -u origin HEAD
    Set-Content -Path $stampFile -Value (Get-Date).ToString('o') -NoNewline
}
finally {
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
}
