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
- O checkout principal só é diferente de `project.root` quando a CLI roda numa worktree ligada (`--git-dir` diferente de `--git-common-dir`); aí ele é a árvore registrada em `core.worktree` do common-dir, se houver, senão o pai do `--git-common-dir`. Fora de worktree ligada (checkout principal, submódulo, `--separate-git-dir`, monorepo com o projeto numa subpasta) continua `project.root`, como hoje.
- `worktree_base`, `misplaced_worktrees` e `validate_worktrees` usam essa raiz para `{repo}`, para resolver caminhos relativos, para `worktree_allow` e para `check-ignore`.
- Com isso, `misplaced_worktrees`, `validate_worktrees`, `worktree_for` e `cmd_worktree` dão o mesmo resultado no checkout principal e em qualquer worktree.
- Cópia em `tools/sdd/spec_graph.py` atualizada com `vendor`; `SDD_TOOL_VERSION`, CHANGELOG da `gluon-spec` e `version` do plugin sobem.
- **Não muda:** o padrão `../{repo}.worktrees`, a chave `worktree_dir`, o modo privado, o ponto de partida da branch (`--base`) nem a lista de worktrees.

**Padrão seguido:** `repo_keys` do mesmo arquivo (checkout principal pelo `--git-common-dir`); testes em `skills/gluon-spec/tests/test_spec_graph.py::WorktreeTest`

**Rollback:** reverter o commit

**Outras ocorrências:** `misplaced_worktrees` (raiz, caminho relativo, `worktree_allow` e `check-ignore`) e `validate_worktrees` (`worktree_dir` dentro do repositório e `.gitignore`) usam a mesma raiz e entram nesta spec pela Emenda v2

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0063:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — `WorktreeTest` já fixa o comportamento a partir do checkout principal e continua passando
- **UT-01** — Dado um repositório com o padrão `../{repo}.worktrees` e uma worktree criada com `worktree SPEC-X --create`, quando `status` e `validate` rodam de dentro dessa worktree, então ela não é acusada como fora do `worktree_dir`, e `worktree SPEC-Y` (sem `--create`) imprime o mesmo caminho que imprime no checkout principal.
- **UT-02** — Dados um submódulo (`super/sub`), um repositório com `--separate-git-dir` e um monorepo com o projeto SDD numa subpasta, quando `worktree SPEC-Y` roda no checkout de cada um, então o caminho é o mesmo de antes desta spec (`super/sub.worktrees/…`, `repo.worktrees/…`, `<subpasta>.worktrees/…`); e dada uma worktree de ferramenta em `.claude/worktrees/x` liberada em `worktree_allow` e um `worktree_dir: .worktrees` fora do `.gitignore`, quando `status` e `validate` rodam de dentro de uma worktree ligada, então a worktree de ferramenta não é acusada e o aviso do `.gitignore` aparece, como no checkout principal.
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
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 5f6bbb7 | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — cf7245c | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 2, após Emenda v2: raiz só em worktree ligada, mesma raiz nas três funções; submódulo, separate-git-dir, monorepo, worktree_allow, .gitignore, worktree_dir absoluto, GIT_DIR e modo privado conferidos; 2 minors, 1 nit e 1 limitação como pendências) — 6584bd9 | 2026-11-16 |
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
| 2 | 2026-11-16 | O checkout principal só difere de `project.root` numa worktree ligada (`core.worktree` ou pai do common-dir); `misplaced_worktrees` e `validate_worktrees` usam a mesma raiz; submódulo, `--separate-git-dir` e monorepo mantêm o caminho de antes; UT-02 novo | G4 rodada 1 (major: regressão em submódulo e `--separate-git-dir`; major: aviso errado de `misplaced_worktrees` de dentro de worktree; minors) | nenhuma | thomas, 2026-11-16 (piloto automático com o recomendado) |
