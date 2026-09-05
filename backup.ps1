# Backup Docker images of the stack into the backups/ folder.
# PowerShell (Windows):  .\backup.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dir = Join-Path $root 'backups'
New-Item -ItemType Directory -Path $dir -Force | Out-Null

$version = (Select-String -Path (Join-Path $root 'django_app\django_app\settings.py') -Pattern "APP_VERSION = '([^']+)'" | ForEach-Object { $_.Matches[0].Groups[1].Value })
if (-not $version) { $version = 'snapshot' }

$images = @(
  'molvestproductounting-django:latest',
  'molvestproductounting-simulator:latest',
  'postgres:16-alpine',
  'nginx:1.27-alpine'
)

foreach ($img in $images) {
  $name = ($img -replace '[:/]', '_')
  $out = Join-Path $dir ("{0}_{1}.tar" -f $name, $version)
  Write-Host "Saving $img -> $out"
  docker save -o $out $img
}

Write-Host "Done. Copies are in backups/"
