# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/).
Cada entrada cita a spec de origem (`SPEC-NNNN`); gere-as com `spec_graph.py report SPEC-NNNN --changelog`.

## [Unreleased]

### Added
- Modo privado, parte 1: `private init|status|off`, registro do usuário (`projects.json`) e `spec_root` fora do repositório, versionado por git próprio com push opcional; `vendor` e `pr-check` recusados em modo privado (SPEC-0003).
- CI do repositório: lint (Ruff 0.17), testes de arquitetura das regras do ADR-0001 e suíte completa em Python 3.9 e 3.15 (SPEC-0001).

### Changed
- Python mínimo da ferramenta passa de 3.8 para 3.9 (o 3.8 está sem suporte desde out/2024); `SDD_TOOL_VERSION` 2026.10.1 (SPEC-0001).
