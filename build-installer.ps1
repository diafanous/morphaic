param([string]$Compiler, [switch]$SkipAppBuild)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $SkipAppBuild) { & .\build-test.ps1 }
    if (-not $Compiler) {
        $candidates = @(
            "$PSScriptRoot\tmp\installer-tools\InnoSetup\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        $Compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $Compiler) { $Compiler = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
    }
    if (-not $Compiler) { throw 'Install Inno Setup 6 or newer, or pass -Compiler with the path to ISCC.exe.' }
    & $Compiler 'windows\morphaic.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Write-Output (Join-Path $PSScriptRoot 'dist\morphaic-1.1.0-setup.exe')
} finally { Pop-Location }
