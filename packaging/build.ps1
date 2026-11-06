param([string]$Version='1.1.0',[string]$ReleaseRoot='', [string]$BuildTemp='')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ReleaseRoot) { $ReleaseRoot = Join-Path $projectRoot 'release' }
if (-not $BuildTemp) { $BuildTemp = Join-Path $PSScriptRoot 'tmp' }
$releaseDir = Join-Path $ReleaseRoot ('祀音-' + $Version)
Push-Location (Join-Path $projectRoot 'app/ui')
try { & npm.cmd run build; if ($LASTEXITCODE) { throw 'Frontend compilation failed' } }
finally { Pop-Location }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$compiledExe = Join-Path $projectRoot 'SiVoiceNew.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll "/win32icon:$projectRoot\app\monitor\si-voice.ico" "/out:$compiledExe" "$projectRoot\app\desktop\Launcher.cs"
if ($LASTEXITCODE) { throw 'Desktop compilation failed. Close the running application before rebuilding.' }
$oldExe = Join-Path $projectRoot '祀音.exe'
$archive = Join-Path $PSScriptRoot 'verification-archive'
New-Item -ItemType Directory -Force $archive | Out-Null
if (Test-Path $oldExe) { Move-Item -LiteralPath $oldExe -Destination (Join-Path $archive ('previous-祀音-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.exe')) }
Move-Item -LiteralPath $compiledExe -Destination $oldExe
& "$projectRoot\app\python\python.exe" -m unittest discover -s "$projectRoot\app\tests" -p 'test_*.py'
if ($LASTEXITCODE) { throw 'Tests failed' }
# Run api_smoke.py, mcp_smoke.py and release_integration.py against a ready backend
# before publishing. The integration test intentionally creates long audio.
$env:TEMP = $BuildTemp
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
$iscc = $env:SIYIN_ISCC
if (-not $iscc) {
    $installed = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($installed) { $iscc = $installed.Source }
}
if (-not $iscc) {
    $candidates = @('D:\GitSoft\Inno Setup 7\ISCC.exe', (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'), (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'))
    $iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $iscc) { throw 'Inno Setup compiler not found. Set SIYIN_ISCC to ISCC.exe.' }
& $iscc /Q "/DSourceRoot=$projectRoot" "/DAppVersion=$Version" "/DReleaseDir=$releaseDir" (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE) { throw 'Installer compilation failed' }
$checksums = Get-ChildItem -LiteralPath $releaseDir -File |
    Where-Object { $_.Extension -in '.exe','.bin' } | Sort-Object Name | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
        "$hash  $($_.Name)"
    }
$checksums | Set-Content -LiteralPath (Join-Path $releaseDir 'SHA256SUMS.txt') -Encoding utf8
