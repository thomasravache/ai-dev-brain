---
id: SPEC-0057
title: "gluon-spec: hook do leak-check sem caminho absoluto da instalação"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-13
parent:
depends_on: [SPEC-0053]
consumes_contract: []
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/assets/hooks/pre-push-leak, skills/gluon-spec/references/private-mode.md, skills/gluon-spec/tests/**, skills/gluon-spec/CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0057 — gluon-spec: hook do leak-check sem caminho absoluto da instalação

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O `pre-push` do leak-check (modo privado) grava o caminho absoluto do `spec_graph.py` que o instalou (`skills/gluon-spec/scripts/spec_graph.py:926`, `Path(__file__).resolve()`). Instalada pelo plugin `fermion`, a skill fica no cache versionado (`…/plugins/cache/fermion-lab/fermion/<versão>/`). Quando uma versão antiga do cache é limpa depois de um update, o hook chama um arquivo que não existe e recusa o push com a mensagem errada ("marcas do SDD encontradas"). Achado M4 da revisão G4 da SPEC-0053.

## 2. Causa Raiz
O hook guarda o caminho da instalação em vez de achar a ferramenta quando roda.

## 3. Mudança Proposta
O hook procura a ferramenta quando roda: primeiro o caminho gravado, se ainda existir; depois `tools/sdd/spec_graph.py` do projeto, se houver. Sem nenhum dos dois, sai com uma mensagem clara: "ferramenta do leak-check não encontrada — rode `private init` de novo". Nunca acusa vazamento por falta da ferramenta.

**Não muda:** a regra do leak-check nem o modo privado.

**Padrão seguido:** geração do hook em `spec_graph.py` (`private init`) e testes de `skills/gluon-spec/tests/`.

**Rollback:** reverter o commit; hooks já instalados continuam com o caminho antigo até o próximo `private init`.

**Outras ocorrências:** conferir os hooks do `vendor --hooks` (`commit-msg`, `pre-commit`), que usam `tools/sdd/` e não o caminho absoluto.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_private_mode` cobre o hook atual.
- **UT-01** — Dado um hook gerado com um caminho que não existe mais, quando ele roda, então sai com a mensagem de ferramenta não encontrada e não diz que há marcas do SDD.
- **IT-01** — Dado um repositório git temporário com o modo privado e o `spec_graph.py` movido depois do `private init`, quando o push roda, então o hook usa `tools/sdd/spec_graph.py` se existir; senão recusa com a mensagem certa.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 e IT-01 em `skills/gluon-spec/tests/` com a tag `SPEC-0057:<ID>`, falhando pelo motivo certo
- [x] Green: hook do leak-check acha a ferramenta quando roda; `SDD_TOOL_VERSION` e CHANGELOG
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dcc2a23 (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=2, skipped=1)); nota: vermelho em e5046e3: LeakHookToolPathTest 2 testes, 2 falhas (o hook chama o spec_graph.py apagado e acusa marcas do SDD); suíte da gluon-spec verde fora deles — e5046e3 | 2026-11-13 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 38e70ce | 2026-11-13 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 38e70ce | 2026-11-13 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (4290f86): APPROVED — hook POSIX, fallback na ordem certa, mensagem sem 'marcas do SDD', espaços e push de remoção conferidos; minors corrigidos como sugerido em f841516 (testes) e 483e2f1: fallback só para tools/sdd não rastreado (o push nunca executa ferramenta versionada pelo time) e escolha da ferramenta só com commit a checar; nits (escape de aspas no caminho gravado, fallback para o cache do plugin) ficam registrados — 483e2f1 | 2026-11-13 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #26 em af7d6ba verde (run 43470182944 ci Python 3.9/3.15, com a checagem de versão do plugin; run 43470205446 sdd/pr-check) — b126727 | 2026-11-13 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-13 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-13 |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
O hook `pre-push` do leak-check (modo privado) acha a ferramenta quando roda: primeiro o caminho gravado no `private init`; se ele sumiu (por exemplo, cache do plugin limpo depois de um update), o `tools/sdd/spec_graph.py` do projeto, mas só se não estiver versionado no git, avisando qual ferramenta rodou. Sem nenhuma, recusa com "ferramenta do leak-check não encontrada — rode `private init` de novo" e nunca mais acusa "marcas do SDD" por falta da ferramenta. Um push que só apaga branches passa sem ferramenta. `SDD_TOOL_VERSION` 2026.11.3.

### Como foi feito
- Modelo `skills/gluon-spec/assets/hooks/pre-push-leak` (sh POSIX, seguro com espaços): função `find_tool`, chamada só na primeira ref com commit a checar; `git ls-files --error-unmatch` recusa o `tools/sdd` rastreado. `install_leak_hook` continua gravando o caminho absoluto como primeira opção.
- Testes em e5046e3 e f841516 (`test_private_mode.py::LeakHookToolPathTest`, simulando o cache do plugin apagado); correção em 4290f86 e 483e2f1; `references/private-mode.md` e CHANGELOG `[2026.11.3]`.
- O Architect ampliou o `touches` para o modelo do hook e o guia do modo privado, que a spec citava e não listava.
- **Revisão G4:** APPROVED; os minors (fallback executaria um `tools/sdd` versionado pelo time e anularia o leak-check; push de remoção recusado sem ferramenta) foram corrigidos com teste antes.

### Prova de Correção
- **Antes (e5046e3, hook de 4290f86^):** `AssertionError: 'ferramenta do leak-check não encontrada' not found in "...can't open file '.../plugins/cache/fermion-lab/fermion/1.0.0/skills/gluon-spec/scripts/spec_graph.py' ... pre-push: marcas do SDD encontradas"` — o hook acusava marcas do SDD por falta da ferramenta.
- **Depois (483e2f1):** `LeakHookToolPathTest` verde (4 testes) e a suíte da `gluon-spec` com 168 testes OK; CI do PR #26 verde.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Hook com caminho gravado inexistente recusa com a mensagem certa, sem 'marcas do SDD' | PASS | `test_private_mode.py::LeakHookToolPathTest` — CI do PR #26 em af7d6ba (run 43470182944, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Por `git push`: sem ferramenta recusa; `tools/sdd` local e ignorado é usado e acha marcas; `tools/sdd` rastreado nunca roda; push de remoção passa | PASS | `LeakHookToolPathTest` — CI do PR #26 em af7d6ba (run 43470182944, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — e5046e3/f841516 vermelhos, 4290f86/483e2f1 verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido — o hook continua gerado por `install_leak_hook` a partir do modelo em `assets/hooks/`
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `references/private-mode.md` e CHANGELOG da `gluon-spec` `[2026.11.3]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — os hooks do `vendor --hooks` usam `tools/sdd/` e não o caminho absoluto; nenhuma

### Deploy
N/A — `SDD_TOOL_VERSION` 2026.11.3 na branch `sdd/SPEC-0056`, PR #26.

### Pendências
Nenhuma nova. Nits registrados na revisão, sem spec: o caminho gravado entra no hook sem escape de aspas (já era assim); um fallback para a versão mais nova do cache do plugin pode vir na frente de auto-melhoria (SPEC-0031).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
