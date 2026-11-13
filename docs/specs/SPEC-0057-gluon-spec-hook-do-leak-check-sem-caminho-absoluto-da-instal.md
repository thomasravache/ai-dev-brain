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
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/CHANGELOG.md]
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
- [ ] Red: UT-01 e IT-01 em `skills/gluon-spec/tests/` com a tag `SPEC-0057:<ID>`, falhando pelo motivo certo
- [ ] Green: hook do leak-check acha a ferramenta quando roda; `SDD_TOOL_VERSION` e CHANGELOG
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dcc2a23 (árvore suja) | 2026-11-13 |
| G1 Red | PENDING | | |
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
