param([Parameter(Mandatory=$true)][string]$ScriptPath)
$ErrorActionPreference = 'Stop'
$application = New-Object -ComObject InDesign.Application
try {
    $script = [IO.File]::ReadAllText($ScriptPath)
    $null = $application.DoScript($script, 1246973031)
} finally {
    if ($application) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application) }
}
