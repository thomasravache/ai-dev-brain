---
id: SPEC-0094
title: "boson-atlas: teste da ordem fina dos logs instável (o kubectl falso recalcula o agora a cada chamada)"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-23
parent:
depends_on: []
consumes_contract: []
touches: [skills/boson-atlas/tests/fixtures/kubernetes/fake_kubectl.py, skills/boson-atlas/tests/test_probe_kubernetes.py, skills/boson-atlas/tests/test_fake_kubectl_clock.py, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-23
---

# SPEC-0094 — boson-atlas: teste da ordem fina dos logs instável (o kubectl falso recalcula o agora a cada chamada)

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O teste `test_lines_are_ordered_by_the_fraction_of_the_second` da SPEC-0089 (UT-03, Emenda v5) falha de vez em quando.

- **Onde falhou:** no CI do PR #70, Python 3.9 (run 45157487271).
- **O que esperava e o que veio:** com `lines: 3`, esperava os ticks `[5, 6, 7]` e recebeu `[2, 3, 5]`.
- **Onde passa:** localmente, em 6 execuções seguidas, e no CI do PR #65.
- **Impacto:** o CI fica vermelho por acaso em qualquer PR, inclusive na `main`, que já tem o teste.

## 2. Causa Raiz
- O `kubectl` falso (`tests/fixtures/kubernetes/fake_kubectl.py`) calcula `NOW = datetime.now(...)` cada vez que o processo começa.
- O adaptador faz um `logs pod/<nome>` por pod, e cada chamada é um processo novo.
- Quando o relógio vira de segundo entre as chamadas, o placeholder de horário com fração de um pod sai um segundo depois do outro.
- Com isso, a ordem entre os pods no teste muda, e as linhas mais recentes deixam de ser as esperadas.
- O adaptador está certo, porque ordena pelo horário que recebe. O defeito é do dublê, que não tem um "agora" único por cenário.

## 3. Mudança Proposta
- `install_kubectl` (em `test_probe_kubernetes.py`) grava no cenário um `now` fixo, em UTC, tirado uma vez na instalação.
- O `kubectl` falso usa esse `now` em todos os placeholders (`now`, `nano`, `frac`). Sem a chave, segue com o relógio, como hoje.
- **Não muda:** o adaptador, o núcleo do probe, as fixtures de resposta e o que cada teste confere.

Este é um defeito de teste. Por isso o "código" corrigido é o próprio dublê, dentro de `tests/`:
- o teste de regressão (`test_fake_kubectl_clock.py`) é escrito antes, pelo test-writer;
- o dublê e o `install_kubectl` são corrigidos depois, em outro commit.

**Padrão seguido:** o cenário `fake-kubectl.json` gravado ao lado do dublê (Emenda v3 da SPEC-0089), que já leva `fixtures`, `fail` e `pod_fail`.

**Rollback:** revert do commit.

**Outras ocorrências:** O `scripted.py` (testes do `verify`) e os adaptadores falsos das probes não usam horário relativo a "agora" entre processos. Nenhuma outra conhecida.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes atuais do adaptador são a caracterização e continuam iguais.
- **UT-01** — Dado o `kubectl` falso instalado com um cenário que traz `now`, quando duas chamadas de `logs` rodam com mais de um segundo entre elas, então os horários impressos para a mesma linha são iguais nas duas (falha antes: o segundo sai deslocado).
- **IT-01** — Dado o `test_lines_are_ordered_by_the_fraction_of_the_second` com o relógio forçado a virar de segundo entre os pods (uma pausa no dublê entre as chamadas), quando o adaptador roda, então a ordem dos ticks é a esperada (falha antes).

## 5. Questões em Aberto
Nenhuma.

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01 e IT-01 com a tag `SPEC-0094:<ID>`, falhando pelo motivo certo (o horário desloca entre chamadas)
- [ ] Green: `now` fixo no cenário gravado por `install_kubectl` e usado pelo `kubectl` falso
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — bd55b01 | 2026-11-23 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — ec73d8b | 2026-11-23 |
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
| 2 | 2026-11-23 | `touches` ganha `.claude-plugin/plugin.json`, porque mudança em `skills/**` (inclusive testes) sobe a versão do plugin (SPEC-0056) | Checagem de versão do plugin no G2 | — | thomas, 2026-11-23 (piloto automático com o recomendado) |
