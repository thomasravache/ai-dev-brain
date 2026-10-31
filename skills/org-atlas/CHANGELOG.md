# Changelog

Todas as mudanças relevantes da skill `org-atlas` são documentadas aqui. Este arquivo viaja com a skill (fica na
pasta dela).

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `ATLAS_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0010, ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`).

## [Unreleased]

## [2026.10.1] - 2026-10-30

### Added
- Skill `org-atlas`: `SKILL.md` com "Antes de qualquer fluxo" (`config`; exit 3 → onboarding) e o onboarding (organização, modo `repo` ou `local`, pasta do atlas, `git init` pelo agente no modo local, credenciais só pelo nome); `references/config.md` e `references/atlas-layout.md`; `assets/atlas-config.yml` padrão e os esqueletos `ATLAS.md` e `glossary.md` com regiões `<!-- atlas:begin/end <nome> -->` em `assets/pages/` (SPEC-0032).
- `scripts/atlas.py` (`ATLAS_VERSION` 2026.10.1, só biblioteca padrão): configuração em duas camadas (`$ATLAS_CONFIG_HOME/config.yml` local e `<atlas>/atlas-config.yml` compartilhada) com a origem de cada valor; `credentials` só com nomes de variável (`^[A-Z_][A-Z0-9_]*$`) e de profile; parser e escritor de YAML próprios; comandos `init` (pasta vazia, repetido igual, `--force` com `.bak`, `--join`), `config [--json]` e `doctor [--json]`, que nunca executa processo nem imprime o valor de uma variável (SPEC-0032).
- Testes de arquitetura do ADR-0010 e suíte da skill na CI (SPEC-0032).
