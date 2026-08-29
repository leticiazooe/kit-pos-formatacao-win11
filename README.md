# Kit Pós-Formatação Windows 11

Kit para acelerar a preparação de um computador recém-formatado com Windows 11, instalando os programas básicos e preparando automaticamente um ambiente Python para desenvolvimento.

## O que instala

### Programas

- Google Chrome
- WinRAR
- Visual Studio Code
- Spotify
- Steam
- Git
- GitHub Desktop
- GitHub CLI (`gh`)
- Python 3.14
- Chocolatey, caso ainda não esteja instalado

### Ambiente Python

O setup atualiza automaticamente:

- `pip`
- `setuptools`
- `wheel`

Depois instala as bibliotecas organizadas por finalidade.

#### Base e automação

- requests
- python-dotenv
- rich
- tqdm
- psutil
- watchdog
- pywin32

#### Dados e Excel

- pandas
- numpy
- openpyxl
- xlsxwriter

#### Web e APIs

- FastAPI
- Uvicorn
- Flask
- SQLAlchemy
- Pydantic
- Beautiful Soup
- Selenium

#### Desktop, PDF e imagem

- PySide6
- CustomTkinter
- pywebview
- Pillow
- PyMuPDF
- OpenCV

#### Desenvolvimento e qualidade

- PyInstaller
- pytest
- Black
- Ruff
- mypy

#### Engenharia e 3D

- trimesh
- numpy-stl

Ao final da instalação das bibliotecas, o script executa `pip check` para detectar conflitos de dependências.

## Como usar

1. Baixe ou clone este repositório.
2. Mantenha toda a estrutura de pastas do projeto.
3. Clique com o botão direito em `executar-setup.cmd`.
4. Escolha **Executar como administrador**.
5. Aceite a solicitação do UAC.
6. Aguarde a instalação dos programas e das bibliotecas Python.

O `.cmd` chama automaticamente o script PowerShell principal.

## Git e GitHub

O kit instala:

- **Git** para versionamento de código.
- **GitHub Desktop** para trabalhar com repositórios por interface gráfica.
- **GitHub CLI** para usar o GitHub diretamente pelo terminal com o comando `gh`.

O login da conta GitHub não é automatizado por segurança. Depois da instalação, você pode autenticar o terminal executando:

```powershell
gh auth login
```

No GitHub Desktop, basta abrir o aplicativo e entrar com a sua conta normalmente.

## Python

O kit usa o pacote `python314` do Chocolatey para manter o ambiente na linha estável do Python 3.14.

As bibliotecas ficam separadas em arquivos `requirements` para facilitar manutenção e permitir adicionar ou remover dependências sem alterar toda a lógica do instalador.

```text
python/
├── requirements-base.txt
├── requirements-data.txt
├── requirements-web.txt
├── requirements-desktop.txt
├── requirements-dev.txt
└── requirements-engineering.txt
```

Se uma categoria falhar, o script registra a falha e continua as demais etapas. O resultado pode ser consultado no log.

## Aplicativos padrão

Ao final, o script abre a tela de **Aplicativos padrão** do Windows 11.

Confirme manualmente:

- Google Chrome para HTTP, HTTPS, `.htm` e `.html`.
- WinRAR para `.rar`, `.zip`, `.7z` e demais formatos compactados desejados.

O Windows 11 protege as associações de aplicativos padrão, por isso o kit evita alterações forçadas no Registro.

## Reexecução e atualização

O script utiliza `choco upgrade` para os programas e `pip install --upgrade` para as bibliotecas Python.

Por isso, ele pode ser executado novamente para:

- instalar itens ausentes;
- atualizar programas já instalados;
- atualizar bibliotecas Python;
- tentar novamente itens que falharam em uma execução anterior.

## Log e tratamento de falhas

Durante a execução é gerado o arquivo:

```text
setup-windows11.log
```

Ele fica na mesma pasta do script e registra a execução para facilitar a identificação de possíveis falhas.

O instalador também apresenta ao final uma lista dos itens que não foram concluídos com sucesso.

## Estrutura

```text
kit-pos-formatacao-win11/
├── executar-setup.cmd
├── setup-windows11.ps1
├── python/
│   ├── requirements-base.txt
│   ├── requirements-data.txt
│   ├── requirements-web.txt
│   ├── requirements-desktop.txt
│   ├── requirements-dev.txt
│   └── requirements-engineering.txt
└── README.md
```

## Observação

A instalação depende de conexão com a internet e dos pacotes externos disponibilizados pelo Chocolatey e pelo PyPI. Caso algum pacote esteja temporariamente indisponível ou ainda não ofereça suporte à versão instalada do Python, o erro ficará registrado no log e o restante do processo continuará.
