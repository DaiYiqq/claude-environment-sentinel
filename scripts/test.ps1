$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent

Push-Location $RepoRoot
try {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }
    node --check sentinel/webui/app.js
    if ($LASTEXITCODE -ne 0) { throw "app.js syntax check failed" }
    node --check docs/assets/site.js
    if ($LASTEXITCODE -ne 0) { throw "site.js syntax check failed" }
}
finally {
    Pop-Location
}
