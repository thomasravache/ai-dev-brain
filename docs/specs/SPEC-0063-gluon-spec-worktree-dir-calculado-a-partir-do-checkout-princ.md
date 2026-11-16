---
id: SPEC-0063
title: "gluon-spec: worktree_dir calculado a partir do checkout principal"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-16
parent:
depends_on: []
consumes_contract: []
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/CHANGELOG.md, tools/sdd/spec_graph.py, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-16
---

# SPEC-0063 — gluon-spec: worktree_dir calculado a partir do checkout principal

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Rodado de dentro de uma worktree, o `spec_graph.py` calcula o `worktree_dir` a partir da própria worktree, não do checkout principal. Reprodução (2026-11-16, verificação manual da SPEC-0058): com o padrão `../{repo}.worktrees`, o `status` rodado em `ai-dev-brain.worktrees/SPEC-0058-…` acusou essa mesma worktree "fora do worktree_dir" e sugeriu `git worktree move <worktree> <worktree>.worktrees/SPEC-0058-…`, ou seja, mover a worktree para dentro dela mesma. O hook de início de sessão (SPEC-0058) repassa esse aviso para o contexto do agente, e um agente que siga a sugestão quebra a worktree. Pelo mesmo motivo, `worktree SPEC-X` e `worktree SPEC-X --create` rodados de dentro de uma worktree apontam para uma pasta aninhada. Esperado: o mesmo resultado de qualquer worktree e do checkout principal.

## 2. Causa Raiz
`worktree_base` (`skills/gluon-spec/scripts/spec_graph.py`) troca `{repo}` por `project.root.name` e resolve o caminho relativo contra `project.root`; dentro de uma worktree, `project.root` é a worktree. `repo_keys`, no mesmo arquivo, já acha o checkout principal pelo pai de `git rev-parse --git-common-dir`.

## 3. Mudança Proposta
- `worktree_base` usa o checkout principal (pai do `--git-common-dir`, como `repo_keys`) para `{repo}` e para resolver o caminho relativo; fora de um repositório git, continua usando `project.root`.
- Com isso, `misplaced_worktrees`, `validate_worktrees`, `worktree_for` e `cmd_worktree` dão o mesmo resultado no checkout principal e em qualquer worktree.
- Cópia em `tools/sdd/spec_graph.py` atualizada com `vendor`; `SDD_TOOL_VERSION`, CHANGELOG da `gluon-spec` e `version` do plugin sobem.
- **Não muda:** o padrão `../{repo}.worktrees`, a chave `worktree_dir`, o modo privado, o ponto de partida da branch (`--base`) nem a lista de worktrees.

**Padrão seguido:** `repo_keys` do mesmo arquivo (checkout principal pelo `--git-common-dir`); testes em `skills/gluon-spec/tests/test_spec_graph.py::WorktreeTest`

**Rollback:** reverter o commit

**Outras ocorrências:** Nenhuma — `repo_keys` já usa o checkout principal; outros usos de `project.root.name` conferidos na revisão

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0063:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — `WorktreeTest` já fixa o comportamento a partir do checkout principal e continua passando
- **UT-01** — Dado um repositório com o padrão `../{repo}.worktrees` e uma worktree criada com `worktree SPEC-X --create`, quando `status` e `validate` rodam de dentro dessa worktree, então ela não é acusada como fora do `worktree_dir`, e `worktree SPEC-Y` (sem `--create`) imprime o mesmo caminho que imprime no checkout principal.
- **IT-01** — Dado o mesmo repositório real em pasta temporária, quando `worktree SPEC-Y --create` roda de dentro da worktree de SPEC-X, então a nova worktree é criada ao lado da primeira em `<repo>.worktrees/`, não dentro dela.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01 e IT-01 em `skills/gluon-spec/tests/` com a tag `SPEC-0063:<ID>`, falhando pelo motivo certo
- [ ] Green: `worktree_base` a partir do checkout principal (pai do `--git-common-dir`)
- [ ] Validar: suíte completa + arquitetura (G2/G3); `vendor` em `tools/sdd/`, `SDD_TOOL_VERSION`, CHANGELOG da `gluon-spec` e `version` do plugin
- [ ] Review independente (G4), integração + CI (G5) e H2, Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — a5ca648 | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — 235917f | 2026-11-16 |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

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
