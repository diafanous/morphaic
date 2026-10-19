param([string]$Name = 'morphaic-1.0.1')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Install the project, desktop and build dependencies in .venv first (uv sync --extra desktop --group build).'
    }
    & $python -m PyInstaller --clean --noconfirm --onefile --windowed --name $Name `
        --add-data 'index.html;.' --add-data 'studio.js;.' --add-data 'controls.js;.' `
        --add-data 'iteration.js;.' --add-data 'ui.css;.' --add-data 'iteration.css;.' --add-data 'glass.css;.' `
        --add-data 'canvas.js;.' --add-data 'templates.js;.' --add-data 'windows/indesign.jsx;windows' --add-data 'windows/run-indesign.ps1;windows' `
        --add-data 'assets;assets' --icon 'assets\morphaic.ico' --version-file 'windows\version-info.txt' `
        --collect-all manifold3d --collect-all rhino3dm --collect-all imageio_ffmpeg --collect-all pillow_heif `
        --exclude-module PIL._imagingft desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'The test build failed.' }
    Write-Output (Join-Path $PSScriptRoot "dist\$Name.exe")
} finally {
    Pop-Location
}
