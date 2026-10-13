#requires -version 5.1
<# Instala/atualiza o Organizador PC como serviço automático no Windows 11. #>
[CmdletBinding()]
param([string] $DownloadsPath = "")
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Abra o PowerShell como administrador e execute novamente.'
    }
}
function Check-Exit([string] $Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step falhou com código $LASTEXITCODE" }
}
Require-Admin
$installRoot = Join-Path $env:ProgramFiles 'OrganizadorPC'
$dataRoot = Join-Path $env:ProgramData 'OrganizadorPC'
$serviceName = 'OrganizadorPC'

if (-not $DownloadsPath) {
    try {
        $shellFolders = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
        $raw = (Get-ItemProperty -Path $shellFolders).'{374DE290-123F-4565-9164-39C4925E467B}'
        $DownloadsPath = [Environment]::ExpandEnvironmentVariables($raw)
    } catch {
        $DownloadsPath = Join-Path $env:USERPROFILE 'Downloads'
    }
}
$DownloadsPath = [IO.Path]::GetFullPath($DownloadsPath)
if (-not (Test-Path -LiteralPath $DownloadsPath -PathType Container)) {
    throw "Pasta Downloads não encontrada: $DownloadsPath"
}
Write-Host "Downloads do usuário: $DownloadsPath" -ForegroundColor Cyan

$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing -and $existing.Status -ne 'Stopped') {
    Stop-Service -Name $serviceName -ErrorAction Stop
    $existing.WaitForStatus('Stopped', '00:00:30')
}

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'organizador_pc') -Destination $installRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'service_windows.py') -Destination $installRoot -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'requirements-windows.txt') -Destination $installRoot -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'abrir-painel.cmd') -Destination $installRoot -Force

$python = Join-Path $installRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -m venv (Join-Path $installRoot '.venv')
    } else {
        $basePython = Get-Command 'python.exe' -ErrorAction SilentlyContinue
        if (-not $basePython) { throw 'Python não encontrado. Execute o kit pós-formatação primeiro.' }
        & $basePython.Source -m venv (Join-Path $installRoot '.venv')
    }
    Check-Exit 'Criar ambiente Python'
}
& $python -m pip install --disable-pip-version-check --upgrade -r (Join-Path $installRoot 'requirements-windows.txt')
Check-Exit 'Instalação do pywin32'

Push-Location $installRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'config.json'))) {
        & $python -m organizador_pc init --downloads $DownloadsPath --storage $dataRoot
        Check-Exit 'Criar configuração'
    } else {
        Write-Host 'Configuração já existe e será preservada (não sobrescrita).' -ForegroundColor Yellow
        & $python -m organizador_pc --config (Join-Path $dataRoot 'config.json') preview | Out-Null
        Check-Exit 'Validar configuração'
    }
    # Somente SYSTEM e Administradores podem alterar regras; usuários podem ler relatórios.
    & icacls.exe $dataRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
    Check-Exit 'Proteger a pasta de configuração'

    & $python (Join-Path $installRoot 'service_windows.py') --startup delayed install
    Check-Exit 'Registrar serviço Windows'
    # Reinício automático pelo Windows após falha inesperada do processo.
    & sc.exe failure $serviceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
    Check-Exit 'Configurar recuperação do serviço'
    Start-Service -Name $serviceName -ErrorAction Stop
} finally {
    Pop-Location
}
Write-Host ''
Write-Host 'Serviço instalado e iniciado com sucesso.' -ForegroundColor Green
Write-Host 'Nome no services.msc: Organizador PC | Downloads'
Write-Host "Painel: $installRoot\abrir-painel.cmd"
Write-Host "Configuração: $dataRoot\config.json"
Write-Host "Relatórios: $dataRoot\reports"
Write-Host 'Obs.: em máquinas com mais de um perfil, cada usuário exige configuração própria.'
