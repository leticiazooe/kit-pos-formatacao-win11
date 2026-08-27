# Kit Pós-Formatação Windows 11

Kit simples para acelerar a preparação de um computador recém-formatado com Windows 11.

## O que instala

- Google Chrome
- WinRAR
- Visual Studio Code
- Spotify
- Steam
- Chocolatey, caso ainda não esteja instalado

## Como usar

1. Baixe ou clone este repositório.
2. Mantenha `executar-setup.cmd` e `setup-windows11.ps1` na mesma pasta.
3. Clique com o botão direito em `executar-setup.cmd`.
4. Escolha **Executar como administrador**.
5. Aceite a solicitação do UAC.
6. Aguarde a instalação dos programas.

## Aplicativos padrão

Ao final, o script abre a tela de **Aplicativos padrão** do Windows 11.

Confirme manualmente:

- Google Chrome para HTTP, HTTPS, `.htm` e `.html`.
- WinRAR para `.rar`, `.zip`, `.7z` e demais formatos compactados desejados.

O Windows 11 protege as associações de aplicativos padrão, por isso o kit evita alterações forçadas no Registro.

## Reexecução

O script utiliza `choco upgrade`, então pode ser executado novamente para instalar itens ausentes ou atualizar os programas já instalados.

## Log

Durante a execução é gerado o arquivo:

```text
setup-windows11.log
```

Ele fica na mesma pasta do script e ajuda a identificar possíveis falhas de instalação.

## Estrutura

```text
kit-pos-formatacao-win11/
├── executar-setup.cmd
├── setup-windows11.ps1
└── README.md
```
