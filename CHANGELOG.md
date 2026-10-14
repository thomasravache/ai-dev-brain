# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/).
Cada entrada cita a spec de origem (`SPEC-NNNN`); gere-as com `spec_graph.py report SPEC-NNNN --changelog`.

## [Unreleased]

### Added
- Modo privado, parte 4: detecção das convenções do time (`private detect`), `pr` no estilo do time sem marcas do SDD, G5 com o comando `ci` e guia `references/private-mode.md` (SPEC-0006).
- Modo privado, parte 3: rastreio sem marcas — commits ligados à spec pela branch, red/green pelos arquivos, testes do plano por `→ caminho::nome`, seção Commits com SHA e patch-id, G7 acha o merge mesmo com squash ou rebase (SPEC-0005).
- `gate G1 --run --at <sha>`: grava o G1 no commit red mesmo com o HEAD já verde; sem `--at`, o G1 aponta o último red (SPEC-0005).
- Modo privado, parte 2: `leak-check` (IDs, tags, seções do SDD, caminho do `spec_root`, padrões do usuário) no diff, nos commits, em mensagens e no nome da branch; hook `pre-push` local; branches neutras no `worktree`; G4 e G5 reprovam com vazamento (SPEC-0004).
- Modo privado, parte 1: `private init|status|off`, registro do usuário (`projects.json`) e `spec_root` fora do repositório, versionado por git próprio com push opcional; `vendor` e `pr-check` recusados em modo privado (SPEC-0003).
- CI do repositório: lint (Ruff 0.17), testes de arquitetura das regras do ADR-0001 e suíte completa em Python 3.9 e 3.15 (SPEC-0001).

### Changed
- Python mínimo da ferramenta passa de 3.8 para 3.9 (o 3.8 está sem suporte desde out/2024); `SDD_TOOL_VERSION` 2026.10.1 (SPEC-0001).
