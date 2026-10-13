#requires -version 5.1
[CmdletBinding()]
param([switch] $RemoverRelatorios)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute como administrador.'
}
$installRoot = Join-Path $env:ProgramFiles 'OrganizadorPC'
$python = Join-Path $installRoot '.venv\Scripts\python.exe'
$script = Join-Path $installRoot 'service_windows.py'
$service = Get-Service -Name 'OrganizadorPC' -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name 'OrganizadorPC'
        $service.WaitForStatus('Stopped', '00:00:30')
    }
    if (-not (Test-Path $python) -or -not (Test-Path $script)) {
        throw 'Serviço encontrado sem os binários. Remova manualmente com sc.exe delete OrganizadorPC.'
    }
    & $python $script remove
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao remover o serviço' }
}
if (Test-Path $installRoot) { Remove-Item -LiteralPath $installRoot -Recurse -Force }
if ($RemoverRelatorios) {
    Remove-Item -LiteralPath (Join-Path $env:ProgramData 'OrganizadorPC') -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Configurações e relatórios também removidos.' -ForegroundColor Yellow
} else {
    Write-Host 'Configurações e relatórios PRESERVADOS no ProgramData\OrganizadorPC.' -ForegroundColor Green
}
Write-Host 'Organizador PC desinstalado. Downloads não foi alterada pela desinstalação.'
