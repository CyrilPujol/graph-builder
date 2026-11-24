# Optional per-user registration. Windows keeps control of the default app.
$ErrorActionPreference = 'Stop'
$appPath = Join-Path $PSScriptRoot 'Graph Builder.exe'
$iconPath = Join-Path $PSScriptRoot 'graphml_document.ico'
if (!(Test-Path $appPath) -or !(Test-Path $iconPath)) {
    throw 'Run this script from the extracted Graph Builder folder.'
}
$classes = 'HKCU:\Software\Classes'
$progId = 'GraphBuilder.GraphML'
New-Item "$classes\$progId\DefaultIcon" -Force | Out-Null
Set-Item "$classes\$progId" -Value 'GraphML graph'
Set-Item "$classes\$progId\DefaultIcon" -Value ('"' + $iconPath + '",0')
New-Item "$classes\$progId\shell\open\command" -Force | Out-Null
Set-Item "$classes\$progId\shell\open\command" -Value ('"' + $appPath + '" "%1"')
New-Item "$classes\.graphml\OpenWithProgids" -Force | Out-Null
New-ItemProperty "$classes\.graphml\OpenWithProgids" -Name $progId -PropertyType String -Value '' -Force | Out-Null
Write-Host 'Graph Builder is registered. Right-click a GraphML file, choose Open with, then Graph Builder and Always. Keep this app folder in place.'
