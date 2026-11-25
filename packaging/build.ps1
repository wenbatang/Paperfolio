param([string]$Uv = (Get-Command uv -ErrorAction Stop).Source, [string]$UvLicenses)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot
$dist = Join-Path $project 'dist'
$work = Join-Path ([IO.Path]::GetTempPath()) ('paperfolio-build-' + [guid]::NewGuid())
$stage = Join-Path $work 'payload'
New-Item -ItemType Directory -Force -Path $stage, $dist | Out-Null
try {
    $files = @('annotations.py','app.py','attachments.py','cloud_translate.py','icons.py','layout.py',
        'library.py','paper_actions.py','reader.py','settings.py','study.py','study_window.py',
        'translate.py','translation_window.py','workspace.py','requirements.txt','requirements-layout.txt',
        'setup.ps1','start.cmd','install-layout.cmd','README.md','SERVICES.md')
    foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $project $name) -Destination $stage }
    $tools = New-Item -ItemType Directory -Path (Join-Path $stage 'tools')
    Copy-Item -LiteralPath $Uv -Destination (Join-Path $tools.FullName 'uv.exe')
    if (-not $UvLicenses) {
        $pythonRoot = Split-Path (Split-Path $Uv)
        $uvMetadata = Get-ChildItem -Path (Join-Path $pythonRoot 'Lib\site-packages\uv-*.dist-info') -Directory |
            Select-Object -First 1
        if (-not $uvMetadata) { throw 'Provide -UvLicenses with the uv LICENSE-APACHE and LICENSE-MIT files.' }
        $UvLicenses = Join-Path $uvMetadata.FullName 'licenses'
    }
    foreach ($name in 'LICENSE-APACHE','LICENSE-MIT') {
        Copy-Item -LiteralPath (Join-Path $UvLicenses $name) -Destination $tools.FullName
    }
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $csc /nologo /codepage:65001 /target:winexe /reference:System.Windows.Forms.dll "/out:$stage\Paperfolio.exe" "$PSScriptRoot\Launcher.cs"
    if ($LASTEXITCODE) { throw 'Launcher build failed' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = Join-Path $work 'payload.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($stage, $archive)
    $exe = Join-Path $dist 'Paperfolio-Setup-x64.exe'
    & $csc /nologo /codepage:65001 /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/resource:$archive,payload.zip" "/out:$exe" "$PSScriptRoot\Installer.cs"
    if ($LASTEXITCODE) { throw 'Installer build failed' }
    $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $dist 'SHA256SUMS.txt'), "$hash  Paperfolio-Setup-x64.exe`n")
    Write-Output $exe
} finally {
    $location = (Resolve-Path -LiteralPath $work).Path
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($location.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $location -Leaf) -match '^paperfolio-build-[0-9a-f-]{36}$') {
        Remove-Item -LiteralPath $location -Recurse -Force
    }
}
