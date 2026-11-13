---
id: ADR-0019
title: Auto-melhoria do plugin só lê e avisa, nunca atualiza sozinha
status: proposed
origin: decision
date: 2026-11-13
pillars: []
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: tests/plugin/test_fermion_doctor.py (SPEC-0061:UT-06) e mcp/tests/test_architecture.py
---

# ADR-0019 — Auto-melhoria do plugin só lê e avisa, nunca atualiza sozinha

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
Depois da troca de nomes (SPEC-0055) e do plugin (SPEC-0053), quem instalou antes fica com cópias antigas das skills ao lado do plugin, `tools/sdd/` e atlas vendorizado velhos e bloco `sdd:start` com o nome antigo. O plugin deve conferir isso quando é usado (radar do thomas, 2026-11-12, SPEC-0031). O que a checagem pode fazer sozinha, e onde ela mora, se cada skill precisa continuar instalável por cópia?

## Direcionadores da Decisão
- Nunca perder trabalho da pessoa: cópias e arquivos vendorizados podem ter edição local.
- Rodar a cada início de sessão sem risco nem demora (sem rede, sem processo).
- Cada skill continua instalável sozinha por cópia (ADR-0001, ADR-0016): a skill não pode depender das outras.
- Mesma fronteira do ADR-0017: hook e servidor MCP chamam scripts como processo, sem importar código.

## Opções Consideradas
- A: script do plugin (`scripts/fermion_doctor.py`), só leitura, que avisa com o comando de atualização; hook e MCP o chamam como processo.
- B: o mesmo script, mas atualizando ou apagando sozinho o que está velho.
- C: um comando de checagem em cada skill (`doctor` de cada uma olhando as outras).

## Resultado da Decisão
**Opção escolhida:** A, porque avisa sempre sem nunca mexer no que é da pessoa, e mantém as skills independentes entre si.

### Consequências
- **Boa**, porque o usuário vê no início de cada sessão o que está velho e o comando exato para resolver.
- **Boa**, porque a checagem não tem efeito colateral e pode rodar em qualquer máquina, inclusive na CI.
- **Ruim**, porque a pessoa ainda precisa rodar o comando; quem ignora o aviso continua com a cópia velha.

### Confirmação (G3)
`tests/plugin/test_fermion_doctor.py` (SPEC-0061:UT-06): `scripts/fermion_doctor.py` só importa a stdlib, não usa `subprocess`, `socket` nem `urllib`, e não escreve, apaga nem move arquivo; cada regra testada contra exemplo e contra o código real. `mcp/tests/test_architecture.py`: o servidor MCP só abre processo para as CLIs das skills e para `scripts/fermion_doctor.py`.

## Prós e Contras das Opções
| Critério (peso) | A: só avisa | B: atualiza sozinho | C: em cada skill |
|---|---|---|---|
| Não perde trabalho da pessoa (3) | sim | não: apaga edição local | sim |
| Skills independentes (2) | sim | sim | não: cada skill conhece as outras |
| Esforço do usuário (1) | roda um comando | nenhum | roda um comando |

## Mais Informações
- https://code.claude.com/docs/en/plugins-reference — `${CLAUDE_PLUGIN_ROOT}` muda a cada versão; pastas de componente da raiz (`hooks/`, `agents/`, `commands/`, `output-styles/`, `monitors/`, `bin/`), então `scripts/` não é carregada como componente — lida em 2026-11-13.
- SPEC-0031 (radar de 2026-11-12), SPEC-0061.
