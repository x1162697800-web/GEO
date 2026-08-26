# 交付启动：先自检，再开客户网站
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
& py -3.12 "$root\geolook\scripts\geo.py" doctor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& py -3.12 "$root\online\server.py" --port 8787 @args
