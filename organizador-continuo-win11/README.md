# Organizador PC — Serviço Automático para Windows 11

**Versão 1.0.0** | Python 3.10+ | Serviço do Windows (`pywin32`) | Painel nativo `Tkinter`

Organiza **arquivos soltos da pasta Downloads** em categorias por extensão, sem remover arquivos existentes. O serviço aparece em `services.msc` como **Organizador PC | Downloads** (`OrganizadorPC`), inicia automaticamente (inicialização automática atrasada) e verifica a pasta a cada **5 minutos**.

Feito para complementar estes projetos:

- [Kit Pós-Formatação Windows 11](https://github.com/leticiazooe/kit-pos-formatacao-win11), que prepara Python e instala bibliotecas; o novo serviço é um componente independente que pode ser instalado depois.
- **Preparador PC v3.0.0**, em `kit-pos-formatacao-win11/pre-formatacao/`, usado como referência nas categorias, históricos e política de não sobrescrever. O repositório `kit-pre-formatacao` estava vazio na data da consulta.

## Funcionalidades

| Função | Comportamento |
| --- | --- |
| Inicialização automática | Serviço Windows independente de sessão/logon, modo de início **Automático (Atrasado)** |
| Organização | Somente arquivos soltos no nível raiz da pasta Downloads, sem abrir subpastas |
| Categorias | PDF, HTML, PASTAS ZIPADAS, IMAGENS, PLANILHAS, WORD, APRESENTACOES, VIDEOS, AUDIOS, INSTALADORES, CODIGO, TEXTO, ATALHOS, OUTROS |
| Segurança | Ignora `.crdownload`, `.part`, `.tmp`, placeholders OneDrive e similares; espera **120 s** e **duas varreduras iguais** antes de mover |
| Colisões | Preserva arquivo antigo e cria `arquivo (1).pdf` quando necessário |
| Sem exclusões | Nunca esvazia lixeira nem elimina arquivos do usuário; apenas move arquivos elegíveis |
| Auditoria | Cada execução relevante gera JSON completo, CSV com eventos e TXT de leitura rápida |
| Histórico | Registra pasta criada, arquivo movido, motivo de ignorado, aguardando e erro |
| Saúde | Grava `status.json` a cada verificação; mantém `service.log` rotativo |
| Painel | Interface Tkinter para ver últimas execuções, prévia, relatórios e exportar resumo diário |
| Configuração | JSON com intervalo, tempo mínimo, Downloads monitorada e modo simulação |

## Instalação no Windows 11

1. Execute primeiro o **kit pós-formatação** para garantir uma instalação do Python.
2. Extraia este projeto em uma pasta local comum (ex.: `C:\Instaladores\OrganizadorPC`).
3. Abra um **PowerShell como Administrador** nessa pasta e rode:

```powershell
.\instalar.ps1
```

Se o Windows bloquear scripts por política de execução, use o `.cmd` fornecido **como administrador**. Para indicar outra pasta de Downloads explicitamente:

```powershell
.\instalar.ps1 -DownloadsPath 'D:\Meus Downloads'
```

O instalador copia o código para `%ProgramFiles%\OrganizadorPC`, cria ambiente Python isolado em `.venv`, instala apenas `pywin32`, cria o arquivo de configuração (se ausente), registra o serviço com inicialização automática atrasada, configura recuperação automática após falhas e inicia o serviço. Rodar novamente atualiza arquivos do programa e preserva configuração/relatórios. **A configuração é criada para um perfil Windows**. Confirme a pasta selecionada, especialmente se usou credenciais de outro administrador no UAC ou redirecionou Downloads para OneDrive.

**Importante:** o instalador requer Windows 11, direitos de administrador, Python com `venv`, `pip` e internet para instalar `pywin32`. Ainda é necessário validar o registro do serviço em um Windows real: os testes automatizados incluídos validam o motor e os relatórios em Python, mas não o Windows Service Control Manager.

## Abrir painel

Dê dois cliques em:

```text
C:\Program Files\OrganizadorPC\abrir-painel.cmd
```

O painel **não fica aberto** para o serviço funcionar. Ele lê os relatórios que o serviço já gerou e oferece prévia sem movimentação.

## Configuração

Local: `%ProgramData%\OrganizadorPC\config.json`.

```json
{
  "downloads_path": "C:\\Users\\SEU_USUARIO\\Downloads",
  "storage_path": "C:\\ProgramData\\OrganizadorPC",
  "interval_seconds": 300,
  "min_age_seconds": 120,
  "dry_run": false,
  "unknown_category": "OUTROS"
}
```

- `interval_seconds`: intervalo entre varreduras (mínimo 10; padrão 300).
- `min_age_seconds`: tempo desde a última modificação, antes de considerar um arquivo (padrão 120).
- `dry_run`: `true` permite simular sem mover; a simulação pode ser feita também por prévia na interface.
- **Edite `config.json` como administrador**, e reinicie o serviço depois. Somente SYSTEM e Administradores devem ter permissão de gravação nessa pasta, pois o serviço executa com permissões elevadas.
- **Nunca habilite organização de toda a unidade C:**. Apenas a pasta Downloads é contemplada.

## Arquivos e relatórios

```text
C:\ProgramData\OrganizadorPC\
├── config.json                     # configuração persistente (administrador)
├── status.json                     # último ciclo / erros / quantidade de arquivos
├── service.log                     # log rotativo
├── scan.lock                       # evita duas varreduras concorrentes
└── reports\
    ├── organizacao_20261010_091500_XXXXXXXX.json
    ├── organizacao_20261010_091500_XXXXXXXX.csv
    └── organizacao_20261010_091500_XXXXXXXX.txt
```

O JSON contém `inicio`, `fim`, `estado`, `resumo`, `por_categoria` e `eventos`. Cada evento inclui: **horário, tipo, nome, categoria, origem, destino, tamanho em bytes e detalhes**. O histórico registra uma execução somente se houve arquivo movido, pasta criada ou erro (ou quando solicitado manualmente), evitando centenas de relatórios vazios.

Não envie logs, config.json nem relatórios reais ao GitHub; podem conter nomes e caminhos privados.

## Comandos úteis

Dentro de `%ProgramFiles%\OrganizadorPC` use o Python da `.venv`:
```powershell
.\.venv\Scripts\python.exe -m organizador_pc status
.\.venv\Scripts\python.exe -m organizador_pc preview
.\.venv\Scripts\python.exe -m organizador_pc run-once
.\.venv\Scripts\python.exe -m organizador_pc daily --date 2026-10-10
.\.venv\Scripts\python.exe -m organizador_pc dashboard
```

`run-once` pode exigir um terminal elevado para criar relatórios em ProgramData. Respeita idade mínima dos arquivos e usa um bloqueio para evitar concorrência com o serviço. `preview` é sempre somente leitura.

Para reiniciar, parar, iniciar e consultar o serviço:

```powershell
Get-Service OrganizadorPC
Restart-Service OrganizadorPC
Stop-Service OrganizadorPC
Start-Service OrganizadorPC
```

## Desinstalação

Em um PowerShell como **Administrador**, a partir da pasta original do projeto:

```powershell
.\desinstalar.ps1
```

Por padrão, **preserva configuração e relatórios**, além de todo o conteúdo de Downloads. Para remover também a pasta privada de relatórios/configuração:

```powershell
.\desinstalar.ps1 -RemoverRelatorios
```

## Segurança e limitações

- O serviço é **local**, sem rede, sem telemetria e sem IA. Não exige navegador nem React.
- O serviço usa a conta padrão **LocalSystem** e por isso pode acessar arquivos locais além do perfil padrão. A configuração é protegida com ACLs de leitura para usuários e gravação restrita a Administradores/SYSTEM. Não use links simbólicos como pasta de destino.
- Serviço Windows e GUI são processos separados. Serviços não devem abrir janelas interativas na sessão do usuário.
- A pasta de Downloads é identificada explicitamente no momento da instalação, porque o usuário do serviço não é o usuário logado. Se mudar de conta ou redirecionar Downloads, revise a configuração.
- Downloads em nuvem (arquivos disponíveis só online são ignorados), rede, unidades desconectadas, arquivos protegidos/abertos ou com nomes especiais podem ser ignorados ou gerar erros. Nenhum arquivo do usuário é excluído intencionalmente.
- Em caso de falha, o erro fica registrado e o ciclo seguinte tenta novamente.
- O serviço não faz backup de arquivos pessoais, não limpa arquivos de sistema nem modifica pastas fora de Downloads. Backup é responsabilidade do **Preparador PC**, usado antes da formatação.

## Desenvolvimento e testes

Sem dependências externas para executar testes:

```powershell
python -m unittest discover -s tests -v
```

O módulo `engine.py` possui toda a lógica de classificação e movimentação. `service_windows.py` contém apenas a integração com o SCM e `ui.py` é o painel Tkinter. Esta separação torna a evolução segura e permite testar a lógica sem iniciar o serviço.

## Melhorias planejadas

Política de limpeza de instaladores antigos **sempre mediante confirmação**, múltiplos perfis Windows, notificações opcionais, exportação XLSX, relatórios por semana/mês e opção de classificação personalizada por extensão.