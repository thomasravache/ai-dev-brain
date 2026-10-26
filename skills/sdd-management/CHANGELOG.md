# Changelog

Todas as mudanças relevantes da skill `sdd-management` são documentadas aqui. Este arquivo viaja com a skill
(fica na pasta dela) e é o que o `spec_graph.py whats-new` mostra aos projetos.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `SDD_TOOL_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`); gere-as com `spec_graph.py report SPEC-NNNN --changelog`.

## [Unreleased]

## [2026.10.12] - 2026-10-26

### Fixed
- `validate` não sugere declarar `h2_policy: auto-on-green` por H2 com o mesmo texto em várias specs quando a política já está declarada e aprovada (`h2_policy_approved_by` e `h2_policy_approved_at` válidos); `SDD_TOOL_VERSION` 2026.10.12 (SPEC-0014).

## [2026.10.11] - 2026-10-26

### Added
- `whats-new [--ack]`: novidades do CHANGELOG da skill desde a versão do projeto, chaves de topo do template do `sdd-config` ausentes no projeto e comandos para se atualizar; chave `sdd_version` no `sdd-config` para projetos sem `tools/sdd`; o `status` avisa quando há novidade (SPEC-0013).

### Changed
- CHANGELOG movido da raiz do repositório para a pasta da skill (`skills/sdd-management/CHANGELOG.md`) e agrupado por versão (SPEC-0013).

## [2026.10.10] - 2026-10-26

### Fixed
- `leak-check` acha o `spec_root` também pelo caminho não resolvido: `HOME` que é link simbólico (absoluto e `~/`) e, no macOS, a forma sem `/private`; `SDD_TOOL_VERSION` 2026.10.10 (SPEC-0012).

## [2026.10.9] - 2026-10-26

### Added
- Documentos vivos: guia de jornadas e mapa do sistema (`living_docs` no sdd-config), comando `living-docs [--init]` com templates agnósticos de stack, avisos do `validate` quando ficam para trás das jornadas críticas e dos ADRs aceitos, e item no G7; `SDD_TOOL_VERSION` 2026.10.9 (SPEC-0011).

## [2026.10.8] - 2026-10-14

### Fixed
- `gate --run --evidence` grava o texto como `nota:` na evidência, como a ajuda descreve; antes era descartado (SPEC-0009).

## [2026.10.7] - 2026-10-14

### Fixed
- `private init` recusa um `spec_root` dentro do próprio repositório, onde as specs ficariam no clone do time (SPEC-0008).

## [2026.10.6] - 2026-10-14

### Fixed
- `pr` não aponta mais quebra só porque a spec teve emenda: o que quebra vem da chave opcional `breaking`; "Como foi feito" começa com maiúscula (SPEC-0007).

## [2026.10.5] - 2026-10-14

### Added
- Modo privado, parte 4: detecção das convenções do time (`private detect`), `pr` no estilo do time sem marcas do SDD, G5 com o comando `ci` e guia `references/private-mode.md` (SPEC-0006).

## [2026.10.4] - 2026-10-14

### Added
- Modo privado, parte 3: rastreio sem marcas — commits ligados à spec pela branch, red/green pelos arquivos, testes do plano por `→ caminho::nome`, seção Commits com SHA e patch-id, G7 acha o merge mesmo com squash ou rebase (SPEC-0005).
- `gate G1 --run --at <sha>`: grava o G1 no commit red mesmo com o HEAD já verde; sem `--at`, o G1 aponta o último red (SPEC-0005).

## [2026.10.3] - 2026-10-14

### Added
- Modo privado, parte 2: `leak-check` (IDs, tags, seções do SDD, caminho do `spec_root`, padrões do usuário) no diff, nos commits, em mensagens e no nome da branch; hook `pre-push` local; branches neutras no `worktree`; G4 e G5 reprovam com vazamento (SPEC-0004).

## [2026.10.2] - 2026-10-14

### Added
- Modo privado, parte 1: `private init|status|off`, registro do usuário (`projects.json`) e `spec_root` fora do repositório, versionado por git próprio com push opcional; `vendor` e `pr-check` recusados em modo privado (SPEC-0003).

## [2026.10.1] - 2026-10-14

### Added
- CI do repositório: lint (Ruff 0.17), testes de arquitetura das regras do ADR-0001 e suíte completa em Python 3.9 e 3.15 (SPEC-0001).

### Changed
- Python mínimo da ferramenta passa de 3.8 para 3.9 (o 3.8 está sem suporte desde out/2024); `SDD_TOOL_VERSION` 2026.10.1 (SPEC-0001).
