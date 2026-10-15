---
id: SPEC-0008
title: Recusar spec_root dentro do repositório
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0008 — Recusar spec_root dentro do repositório

## 1. Problema
`private init --spec-root <caminho>` aceita um caminho **dentro** do próprio repositório do time (ex.: `--spec-root ./notas`). As specs passam a ficar no clone, a um `git add -A` de serem commitadas — o vazamento que o modo privado existe para evitar. Achado na revisão (G4) da SPEC-0003.

## 2. Causa Raiz
`cmd_private` (ação `init`) resolve o caminho e cria a pasta sem comparar com a raiz do repositório.

## 3. Mudança Proposta
`private init` recusa (exit 2) um `spec_root` que seja o repositório ou fique dentro dele, citando a raiz e sugerindo o padrão (`<default_root>/<org>/<repo>`). O registro não muda. Não muda: `spec_root` fora do repositório, inclusive vizinho (`../sdd`).

**Padrão seguido:** demais recusas de `cmd_private` (repositório com `docs/specs` versionado → exit 2 com mensagem), testes em `test_private_mode.py`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — o registro só é escrito pelo `private init`.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_init_registers_and_creates_versioned_spec_root` já fixa o caso válido e continua passando.
- **UT-01** — Dado um repositório sem modo privado, quando roda `private init --spec-root <repo>/notas` (e `--spec-root <repo>`), então sai com 2, a mensagem cita o repositório, nenhuma pasta é criada e o registro não muda; com `--spec-root <tmp>/fora`, funciona.
- Integração/E2E: N/A — UT-01 já roda o comando pela CLI num repositório temporário.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [x] Red: UT-01 com a tag `SPEC-0008:UT-01`, falhando pelo motivo certo
- [x] Green: correção mínima, seguindo o padrão citado
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `SDD_TOOL_VERSION` e CHANGELOG (ADR-0005)
- [x] Review (G4), integração (G5, bypass local enquanto a CI estiver bloqueada) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 33c9a60 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=1, skipped=1)) — 86f934b | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 407c0e5 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 407c0e5 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major/minor; checagem antes de gravar o registro, pelo caminho da worktree principal (vale também rodando de uma worktree) — 407c0e5 | 2026-10-14 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do GitHub verde no PR #3 em ee02ae2: ci 3.9 e 3.15 (run 38677000910) e sdd/pr-check (run 38677000897) — substitui o bypass local — 196c3a7 | 2026-10-15 |
| H2 Integração aprovada | PASS | aprovado por thomas — autorizou os merges em 2026-10-15 ('pode ir seguindo com os merges quando tudo passar'), com G5 verde na CI do GitHub | 2026-10-15 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 1e08452 | 2026-10-15 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G1 | decisão | Onda aguarda o H2 das specs abertas (SPEC-0001, 0003–0006), adiado: merges ficam para depois e o GitHub Actions está bloqueado (IMP-02) | waves/next: arquivos em comum com specs em andamento | thomas | thomas autorizou em 2026-10-14 continuar todas as implementações antes dos merges ('precisamos continuar todas as implementações'); base: sdd/SPEC-0002, que já contém as specs anteriores | 2026-10-14 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
`private init` recusa um `spec_root` dentro do próprio repositório, onde as specs ficariam no clone do time.

### Como foi feito
Comparação do caminho resolvido do `spec_root` com a raiz do repositório antes de gravar o registro.

### Prova de Correção
Red: commit 86f934b — `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (FAILED (failures=1, skipped=1)), registrado no G1. Green: commit 407c0e5 — suíte exit 0 (OK) no G2, e verde na CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Dado um repositório sem modo privado, quando roda `private init --spec-root <repo>/notas` (e `--spec-root <repo>`), então sai com 2, a… | PASS | `test_private_mode.py::test_spec_root_inside_the_repository_is_refused` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — modo solo (projeto de um mantenedor); merge aprovado por thomas (H2)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: pilar entrega dispensado; vale na `main` pelo link simbólico
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado): passa a valer na `main` com o merge do PR #3, pelo link simbólico `~/.claude/skills/sdd-management`. Versão da ferramenta 2026.10.8. Rollback: revert do merge.

### Pendências
Nenhuma. A cópia `tools/sdd` é atualizada em PR próprio depois do merge (ADR-0005).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
