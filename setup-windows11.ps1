#requires -version 5.1
<#
    SETUP WINDOWS 11 - POS-FORMATACAO

    Instala automaticamente:
      - Google Chrome
      - WinRAR
      - Visual Studio Code
      - Spotify
      - Steam
      - Git
      - GitHub Desktop
      - GitHub CLI
      - Python 3.14
      - Bibliotecas Python usadas nos projetos

    Tambem abre a configuracao de Aplicativos Padrao ao final.
#>

$ErrorActionPreference = "Stop"

function Write-Title {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " $Text" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Test-Administrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Refresh-Path {
    $env:Path = (
        [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [System.Environment]::GetEnvironmentVariable("Path", "User")
    )
}

if (-not (Test-Administrator)) {
    Write-Host "Solicitando permissao de Administrador..." -ForegroundColor Yellow

    $arguments = @(
        "-NoProfile"
        "-ExecutionPolicy", "Bypass"
        "-File", "`"$PSCommandPath`""
    )

    Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
    exit
}

$logPath = Join-Path $PSScriptRoot "setup-windows11.log"
try {
    Start-Transcript -Path $logPath -Append | Out-Null
} catch {
}

Clear-Host
Write-Title "SETUP WINDOWS 11"

Write-Host "Este script vai preparar o computador apos a formatacao." -ForegroundColor White
Write-Host ""
Write-Host "Programas:" -ForegroundColor Gray
Write-Host "  [1] Google Chrome"
Write-Host "  [2] WinRAR"
Write-Host "  [3] Visual Studio Code"
Write-Host "  [4] Spotify"
Write-Host "  [5] Steam"
Write-Host "  [6] Git"
Write-Host "  [7] GitHub Desktop"
Write-Host "  [8] GitHub CLI"
Write-Host "  [9] Python 3.14"
Write-Host " [10] Bibliotecas Python"
Write-Host ""

Write-Title "1/4 - CHOCOLATEY"

if (-not (Get-Command choco.exe -ErrorAction SilentlyContinue)) {
    Write-Host "Chocolatey nao encontrado. Instalando..." -ForegroundColor Yellow

    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol =
        [System.Net.ServicePointManager]::SecurityProtocol -bor 3072

    Invoke-Expression (
        (New-Object System.Net.WebClient).DownloadString(
            'https://community.chocolatey.org/install.ps1'
        )
    )

    Refresh-Path
} else {
    Write-Host "Chocolatey ja esta instalado." -ForegroundColor Green
}

if (-not (Get-Command choco.exe -ErrorAction SilentlyContinue)) {
    throw "Chocolatey nao ficou disponivel no PATH. Feche o terminal, abra novamente como Administrador e execute o script."
}

choco --version

Write-Title "2/4 - INSTALANDO PROGRAMAS"

$packages = @(
    @{ Id = "googlechrome";    Name = "Google Chrome" },
    @{ Id = "winrar";         Name = "WinRAR" },
    @{ Id = "vscode";         Name = "Visual Studio Code" },
    @{ Id = "spotify";        Name = "Spotify" },
    @{ Id = "steam";          Name = "Steam" },
    @{ Id = "git";            Name = "Git" },
    @{ Id = "github-desktop"; Name = "GitHub Desktop" },
    @{ Id = "gh";             Name = "GitHub CLI" },
    @{ Id = "python314";      Name = "Python 3.14" }
)

$failed = @()
$restartRecommended = $false

foreach ($package in $packages) {
    Write-Host ""
    Write-Host ">>> $($package.Name)" -ForegroundColor Cyan

    & choco.exe upgrade $package.Id -y --no-progress
    $exitCode = $LASTEXITCODE

    if ($exitCode -in @(0, 1605, 1614, 1641, 3010)) {
        Write-Host "$($package.Name): OK" -ForegroundColor Green

        if ($exitCode -in @(1641, 3010)) {
            $restartRecommended = $true
        }
    } else {
        Write-Host "$($package.Name): FALHOU (codigo $exitCode)" -ForegroundColor Red
        $failed += $package.Name
    }
}

Refresh-Path

Write-Host ""
if (Get-Command git.exe -ErrorAction SilentlyContinue) {
    Write-Host "Git instalado: $(git --version)" -ForegroundColor Green
}

if (Get-Command gh.exe -ErrorAction SilentlyContinue) {
    $ghVersion = (gh --version | Select-Object -First 1)
    Write-Host "GitHub CLI instalado: $ghVersion" -ForegroundColor Green
}

Write-Title "3/4 - PREPARANDO PYTHON"

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue

if (-not $pythonCommand) {
    Refresh-Path
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}

if (-not $pythonCommand) {
    Write-Host "Python nao ficou disponivel no PATH." -ForegroundColor Red
    $failed += "Python / bibliotecas Python"
} else {
    $pythonExe = $pythonCommand.Source
    Write-Host "Python encontrado em: $pythonExe" -ForegroundColor Green
    & $pythonExe --version

    Write-Host ""
    Write-Host "Atualizando pip, setuptools e wheel..." -ForegroundColor Cyan
    & $pythonExe -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Falha ao atualizar ferramentas base do Python." -ForegroundColor Red
        $failed += "pip/setuptools/wheel"
    }

    $requirementsDir = Join-Path $PSScriptRoot "python"
    $requirementsFiles = @(
        "requirements-base.txt",
        "requirements-data.txt",
        "requirements-web.txt",
        "requirements-desktop.txt",
        "requirements-dev.txt",
        "requirements-engineering.txt"
    )

    foreach ($requirementsFile in $requirementsFiles) {
        $requirementsPath = Join-Path $requirementsDir $requirementsFile

        Write-Host ""
        Write-Host ">>> Instalando $requirementsFile" -ForegroundColor Cyan

        if (-not (Test-Path $requirementsPath)) {
            Write-Host "Arquivo nao encontrado: $requirementsPath" -ForegroundColor Red
            $failed += $requirementsFile
            continue
        }

        & $pythonExe -m pip install --upgrade -r $requirementsPath
        if ($LASTEXITCODE -eq 0) {
            Write-Host "$requirementsFile: OK" -ForegroundColor Green
        } else {
            Write-Host "$requirementsFile: FALHOU" -ForegroundColor Red
            $failed += $requirementsFile
        }
    }

    Write-Host ""
    Write-Host "Verificando dependencias instaladas..." -ForegroundColor Cyan
    & $pythonExe -m pip check
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Ambiente Python sem conflitos reportados pelo pip." -ForegroundColor Green
    } else {
        Write-Host "O pip encontrou conflitos de dependencias. Consulte o log." -ForegroundColor Yellow
        $failed += "pip check"
    }
}

Write-Title "4/4 - APLICATIVOS PADRAO"

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chromePath = $chromeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($chromePath) {
    Write-Host "Solicitando ao Chrome que seja definido como navegador padrao..." -ForegroundColor Yellow
    try {
        Start-Process -FilePath $chromePath -ArgumentList "--make-default-browser"
    } catch {
        Write-Host "Nao foi possivel iniciar a solicitacao automatica do Chrome." -ForegroundColor DarkYellow
    }
}

Write-Host ""
Write-Host "Abrindo Aplicativos Padrao do Windows 11..." -ForegroundColor Yellow
Write-Host "Confirme:" -ForegroundColor White
Write-Host "  - Google Chrome -> HTTP, HTTPS, .HTM e .HTML"
Write-Host "  - WinRAR -> .RAR, .ZIP, .7Z e demais formatos que voce quiser"
Write-Host ""

try {
    Start-Process "ms-settings:defaultapps"
} catch {
    Write-Host "Abra manualmente: Configuracoes > Aplicativos > Aplicativos padrao." -ForegroundColor Yellow
}

Write-Title "CONCLUIDO"

if ($failed.Count -eq 0) {
    Write-Host "Todos os programas e bibliotecas foram instalados/atualizados com sucesso." -ForegroundColor Green
} else {
    Write-Host "Os seguintes itens tiveram erro:" -ForegroundColor Red
    foreach ($item in ($failed | Select-Object -Unique)) {
        Write-Host "  - $item" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "Voce pode executar este script novamente. Os itens corretos serao mantidos e os demais serao tentados novamente." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "GitHub Desktop e GitHub CLI foram instalados, mas o login na sua conta GitHub continua sendo feito por voce." -ForegroundColor Cyan
Write-Host "Para autenticar o terminal depois, use: gh auth login" -ForegroundColor Cyan

if ($restartRecommended) {
    Write-Host ""
    Write-Host "Um dos instaladores recomendou reiniciar o Windows." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Log: $logPath" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Pressione ENTER para fechar..." -ForegroundColor Gray
[void](Read-Host)

try {
    Stop-Transcript | Out-Null
} catch {
}
