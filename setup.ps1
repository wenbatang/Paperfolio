param([string]$Python, [string]$IndexUrl = 'https://pypi.org/simple', [switch]$Layout)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$requirements = if ($Layout) { 'requirements-layout.txt' } else { 'requirements.txt' }
$uv = if (Test-Path -LiteralPath '.\tools\uv.exe') { (Resolve-Path -LiteralPath '.\tools\uv.exe').Path }
      else { (Get-Command uv -ErrorAction SilentlyContinue).Source }
if ($uv) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (-not $Python) { $Python = '3.12' }
        & $uv venv --python $Python .venv
        if ($LASTEXITCODE) { exit $LASTEXITCODE }
    }
    & $uv pip install --python $venvPython --default-index $IndexUrl -r $requirements
} else {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($Python) { & $Python -m venv .venv }
        elseif (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv .venv }
        else { python -m venv .venv }
        if ($LASTEXITCODE) { exit $LASTEXITCODE }
    }
    & $venvPython -m pip install --index-url $IndexUrl -r $requirements
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $venvPython -c "import tkinter, sqlite3, pymupdf, PIL"
exit $LASTEXITCODE
