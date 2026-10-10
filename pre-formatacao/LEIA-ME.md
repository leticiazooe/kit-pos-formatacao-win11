# Preparador PC v3.0.0

Assistente **pré-formatação** para Windows, escrito em Python e com interface nativa **Tkinter/ttk**. Não usa React, navegador, servidor local ou PyWebView. Para executar o código, basta Python 3.10+ com Tk.

## Executar

No Windows, dentro desta pasta:

```powershell
py -3 preparador_pc.py
```

Se `py` não estiver disponível, use `python preparador_pc.py`. **Não execute como administrador**, a menos que exista uma necessidade específica de acesso a arquivos.

## Abas

1. **Organizar Downloads:** categoriza arquivos soltos por extensão. Exibe prévia antes da mudança, não sobrescreve nomes e ignora arquivos de download incompletos. A organização MOVE arquivos dentro de Downloads; faça backup antes se eles forem importantes.
2. **Fazer backup:** permite selecionar Capturas de Tela, Área de Trabalho, Documentos, Imagens, Downloads **e qualquer pasta personalizada**. Selecione o destino em dispositivo diferente do que será formatado. A cópia preserva as pastas originais e compara SHA-256 de origem e destino.
3. **Histórico:** registra por organização pastas criadas/reutilizadas, arquivos movidos, pastas preservadas, ignorados e erros. Permite buscar, filtrar e exportar para TXT/CSV/JSON.
4. **Inventário e VS Code:** exporta programas instalados (nome, versão, fabricante) em TXT/CSV/JSON. Exporta extensões VS Code e **somente** as configurações marcadas (`settings.json`, `keybindings.json`, `snippets/`), com um relatório da operação.
5. **Checklist:** itens a validar antes de formatar.

## Como conferir o backup

1. Clique em **Adicionar pasta** em Fazer backup para incluir qualquer diretório fora dos caminhos padrão. Pastas selecionadas aparecem na lista.
2. Escolha o HD externo ou outro dispositivo físico como destino; clique em **Iniciar backup**.
3. A execução cria `PreparadorPC_AAAAMMDD_HHMMSS/` com subpastas por categoria, sem substituir backups anteriores.
4. Confira `relatorio_backup.json`, `relatorio_backup.csv` e `resumo_backup.txt` no destino.
5. Clique em **Visualizar relatório de backup** na interface e selecione o `relatorio_backup.json` gerado. A janela exibe **status**, origem, destino e motivo de falhas ou itens ignorados, com exportação CSV.
6. Abra manualmente arquivos relevantes diretamente no backup antes de formatar.

Os estados do backup são `concluido`, `concluido_com_pendencias`, `cancelado` ou `erro_espaco_insuficiente`. Backups parciais **não** indicam segurança para formatar. Arquivos só na nuvem são ignorados e registrados; baixe-os antes pelo OneDrive.

## Inventário de programas

Na aba Inventário clique em **Exportar inventário**. O programa lê entradas de desinstalação do Registro do Windows (usuário atual, máquina, 32/64 bits) e gera nomes, versões e fabricantes. **Não** coleta instaladores, números de série, licenças ou senhas. Pode não cobrir apps portáteis, alguns aplicativos da Microsoft Store ou programas instalados em outros perfis de usuário.

## VS Code

1. Escolha a pasta de configurações. O padrão no Windows é `%APPDATA%\Code\User`.
2. Escolha uma pasta de destino de backup fora da pasta de configurações.
3. Marque as configurações desejadas: `settings.json`, `keybindings.json`, `snippets/`. Por segurança, **settings.json começa desmarcado**.
4. Clique em **Exportar ambiente VS Code**. O programa tenta consultar `code --list-extensions --show-versions`; se a CLI não estiver disponível, consulta os manifestos locais em `~/.vscode/extensions`.
5. O diretório de saída contém `extensoes_vscode.txt`, `extensoes_vscode.json`, `configuracoes/` (quando selecionada), `relatorio_vscode.json` e `LEIA-ME.txt`.

A lista de extensões é para reinstalação manual, por exemplo `code --install-extension publisher.extension`. O programa **não instala nem restaura automaticamente** o VS Code.

**Privacidade:** `settings.json` pode conter senhas, tokens e URLs privadas. Nunca envie arquivos de backup, configurações pessoais ou históricos com caminhos privados a repositórios públicos. Só o código-fonte e os testes devem entrar no GitHub.

## Histórico de organização

`Downloads\_RELATORIOS_PREPARADOR_PC` armazena JSON por execução. Esse local também pode ser formatado: exporte os históricos importantes para a unidade de backup.

## Limitações e segurança

- Não formata discos, remove dados originais, gera imagens completas do Windows nem recupera credenciais.
- O organizador MOVE arquivos; o backup COPIA e confere hashes. Sempre faça backup antes de organizar pastas críticas.
- Diferentes letras de unidade podem pertencer ao mesmo disco físico. Prefira mídia de backup fisicamente separada.
- Arquivos ausentes, inacessíveis, simbólicos ou só na nuvem são registrados como ignorados/erros conforme o contexto; esses arquivos não serão preservados no backup.
- Não faz backup automático de navegadores, chaves BitLocker, bancos de dados em execução ou configurações de outros aplicativos.
- O código é multiplataforma para testes e parte das operações, mas o inventário de programas utiliza o **Registro do Windows**. A validação final deve ocorrer em um Windows real antes de usar para formatação.

## Testes

```powershell
python -m unittest discover -v
```

## Executável Windows (opcional)

```powershell
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name PreparadorPC preparador_pc.py
```

O Python puro não possui dependências externas de execução; PyInstaller é opcional e serve apenas para criar um `.exe`.