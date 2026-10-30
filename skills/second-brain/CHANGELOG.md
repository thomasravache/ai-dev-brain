# Changelog

Todas as mudanças relevantes da skill `second-brain` são documentadas aqui. Este arquivo viaja com a skill (fica na
pasta dela).

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `BRAIN_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0007, ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`).

## [Unreleased]

## [2026.10.1] - 2026-10-30

### Added
- Skill `second-brain`: `SKILL.md` com o onboarding (vault novo, `--adopt`, `init --join`) e o uso direto quando configurado; `references/config.md`, `providers.md` (Google Drive, OneDrive, iCloud e pasta local, com avisos de iOS e Android) e `vault-layout.md`; modelos de nota e `brain-config.yml` padrão em `assets/` (SPEC-0017).
- `scripts/brain.py` (`BRAIN_VERSION` 2026.10.1, só biblioteca padrão): configuração em duas camadas (`$BRAIN_CONFIG_HOME/config.yml` local e `<vault>/brain-config.yml` compartilhada) com a origem de cada valor; comandos `init` (novo, `--adopt` com `--map`, `--context`, `--force` com `.bak`, `--join`), `config [--json]`, `context add` e `doctor [--json]`; toda escrita no vault registrada no `log.md` (SPEC-0017).
