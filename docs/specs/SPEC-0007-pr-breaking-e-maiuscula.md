---
id: SPEC-0007
title: "PR do modo completo: breaking changes falso e texto em minúscula"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/references/template-full.md, CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0007 — PR do modo completo: breaking changes falso e texto em minúscula

## 1. Problema
No modo completo, `spec_graph.py pr` erra em dois pontos, achados ao abrir os PRs #1 e #3:
- **Breaking changes falso:** toda spec com `contract_version` > 1 aparece como possível quebra ("Contrato em v2 — ver Emendas da spec. Se quebra consumidores, marque `!`…"), mesmo quando a emenda é compatível (SPEC-0001 v2 e SPEC-0004 v2). Foi preciso corrigir os corpos dos PRs à mão.
- **"Como foi feito" em minúscula:** sem Relatório de Entrega, o texto vem do rótulo `**Decisão:**` da spec, que costuma continuar a frase em minúscula ("um workflow novo…"), e a seção do PR começa em minúscula.

Impacto: PR com informação errada sobre compatibilidade e texto mal formatado; o usuário precisa editar o corpo gerado.

## 2. Causa Raiz
`pr_breaking` (`spec_graph.py`) trata `contract_version > 1` como sinal de quebra, mas a versão só diz que houve emenda; se a emenda quebra consumidores não está registrado em lugar nenhum. `pr_how` devolve o texto do rótulo sem ajustar a primeira letra.

## 3. Mudança Proposta
- Chave opcional `breaking` no frontmatter da spec (texto: o que quebra e como migrar). `pr_breaking` mostra esse texto quando existe; sem ela, "Nenhuma" — e, com `contract_version` > 1, "Nenhuma (contrato em vN; emendas compatíveis — ver Emendas)".
- `pr_how` (e o resumo do PR) começam com letra maiúscula.
- O template full ganha `breaking:` comentado no frontmatter, explicando quando usar.
Não muda: título do PR, `pr-check`, modo privado.

**Padrão seguido:** demais funções `pr_*` em `spec_graph.py` (uma função por seção, testes em `test_spec_graph.py` com o `Project` temporário).

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — o resumo do PR já usa texto de seção inteira, que começa em maiúscula.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o `pr` já é coberto por `test_pr_out_prints_only_the_title` e `test_pr_check_ignores_narrative_refs_and_exempts_root_docs`, que continuam passando.
- **UT-01** — Dado uma spec com `contract_version: 2` sem `breaking`, quando o corpo do PR é gerado, então "Breaking changes" diz "Nenhuma (contrato em v2; emendas compatíveis — ver Emendas)"; com `breaking: "remove o campo X; migre para Y"`, então mostra esse texto; e dado `**Decisão:** um workflow novo`, então "Como foi feito" começa com "Um workflow novo".
- Integração/E2E: N/A — a função é pura sobre o texto da spec; UT-01 roda o comando `pr` pela CLI num repositório temporário.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [ ] Red: UT-01 com a tag `SPEC-0007:UT-01`, falhando pelo motivo certo
- [ ] Green: correção mínima, seguindo o padrão citado
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `SDD_TOOL_VERSION` e CHANGELOG (ADR-0005)
- [ ] Review (G4), integração (G5, bypass local enquanto a CI estiver bloqueada) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 983a922 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=1, skipped=1)) — bd1b514 | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 11c8349 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 11c8349 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major/minor; diff mínimo no padrão das funções pr_*; TEST_DEFECT de aspas corrigido em commit test próprio (907b3cd) — 11c8349 | 2026-10-14 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do GitHub verde no PR #3 em ee02ae2: ci 3.9 e 3.15 (run 38677000910) e sdd/pr-check (run 38677000897) — substitui o bypass local — c99363e | 2026-10-15 |
| H2 Integração aprovada | PASS | aprovado por thomas — autorizou os merges em 2026-10-15 ('pode ir seguindo com os merges quando tudo passar'), com G5 verde na CI do GitHub | 2026-10-15 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-15 |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G1 | decisão | Onda aguarda o H2 das specs abertas (SPEC-0001, 0003–0006), adiado: merges ficam para depois e o GitHub Actions está bloqueado (IMP-02) | waves/next: arquivos em comum com specs em andamento | thomas | thomas autorizou em 2026-10-14 continuar todas as implementações antes dos merges ('precisamos continuar todas as implementações'); base: sdd/SPEC-0002, que já contém as specs anteriores | 2026-10-14 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
