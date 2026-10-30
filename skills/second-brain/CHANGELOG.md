# Changelog

Todas as mudanças relevantes da skill `second-brain` são documentadas aqui. Este arquivo viaja com a skill (fica na
pasta dela).

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `BRAIN_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0007, ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`).

## [Unreleased]

## [2026.10.2] - 2026-10-30

### Added
- Comandos de só leitura `search QUERY [--context] [--type] [--tag] [--limit] [--json]` (TF-IDF com peso 3 no título, 2 nas tags e 1 no corpo, sem acentos e sem stopwords pt/en, trecho de até 160 caracteres), `related (--note | --text) [--limit] [--json]` (cosseno TF-IDF, tags em comum, mesmo contexto e vizinhança de links, com os motivos) e `links NOTA [--json]` (saída, backlinks e quebrados) no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.2) (SPEC-0018).
- Leitura de notas (`parse_note`, `scan_vault`) com frontmatter, título, tags (frontmatter e `#tag` fora de código) e wikilinks, e resolução de links como o Obsidian (`resolve_link`: nome sem diferenciar maiúsculas, caminho com `/`, o mais curto nos empates); ignora `.obsidian/`, `.trash/`, a pasta de templates e o que não é `.md`; frontmatter inválido ou arquivo que não é UTF-8 vira aviso em `warnings` sem derrubar o comando (SPEC-0018).
- `SKILL.md`: quando usar `search`, `related` e `links` nos fluxos de guardar e de consultar; `references/search.md` com a pontuação e os filtros (SPEC-0018).

## [2026.10.1] - 2026-10-30

### Added
- Skill `second-brain`: `SKILL.md` com o onboarding (vault novo, `--adopt`, `init --join`) e o uso direto quando configurado; `references/config.md`, `providers.md` (Google Drive, OneDrive, iCloud e pasta local, com avisos de iOS e Android) e `vault-layout.md`; modelos de nota e `brain-config.yml` padrão em `assets/` (SPEC-0017).
- `scripts/brain.py` (`BRAIN_VERSION` 2026.10.1, só biblioteca padrão): configuração em duas camadas (`$BRAIN_CONFIG_HOME/config.yml` local e `<vault>/brain-config.yml` compartilhada) com a origem de cada valor; comandos `init` (novo, `--adopt` com `--map`, `--context`, `--force` com `.bak`, `--join`), `config [--json]`, `context add` e `doctor [--json]`; toda escrita no vault registrada no `log.md` (SPEC-0017).
- Proteções do vault (SPEC-0017, emenda v2): valores de `layout`, `para` e `contexts.<c>.folder` fora do vault (absolutos ou com `..`) fazem os comandos saírem com 1 e aparecem como ERRO no `doctor`; `init` recusa pasta não vazia sem `--adopt` e não adota `log.md`/`index.md` do usuário (`--map log=<outro>`); `brain-config.yml` gerado a partir de `assets/brain-config.yml` com os comentários; `context add` só insere a linha nova em `contexts`, com a indentação existente, e recusa `contexts` inline; `doctor` continua com `brain-config.yml` ilegível; `providers.md` só afirma o que a fonte verificada do ADR-0008 diz.
