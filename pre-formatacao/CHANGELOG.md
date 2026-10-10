# Histórico de versões — Preparador PC

## 3.0.0 — 2026-10-10

- Cria aba **Inventário e VS Code**, sem bibliotecas externas.
- Amplia exportação de aplicativos instalados para TXT, CSV e JSON.
- Exporta extensões do VS Code com versão quando disponível; usa manifestos locais como contingência.
- Permite selecionar apenas configurações desejadas de VS Code; `settings.json` vem desmarcado por segurança.
- Mantém backup de pastas adicionais e torna a auditoria consultável pela interface, com CSV, JSON e resumo TXT.
- Registra itens copiados/verificados, ignorados, arquivos de links simbólicos e falhas da varredura.
- Amplia suíte de testes de 7 para 12 casos, incluindo regressão de caminhos redirecionados no Windows, e adiciona instruções de recuperação.

## 2.0.0 — 2026-10-10

- Histórico detalhado da organização de Downloads, filtros, busca e exportações.

## 1.0.0 — 2026-10-10

- Organizador de Downloads, backup com SHA-256, seleção de pastas, inventário TXT e checklist.