---
id: SPEC-0043
title: "org-atlas: testes do endurecimento do init e do doctor e regra de processo com alias"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0032]
consumes_contract: []
touches: [skills/org-atlas/tests/architecture_rules.py, skills/org-atlas/tests/test_architecture.py, skills/org-atlas/tests/test_hardening.py, skills/org-atlas/scripts/atlas.py, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0002]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0043 — org-atlas: testes do endurecimento do init e do doctor e regra de processo com alias

## 1. Problema
Duas pendências da revisão (G4) da SPEC-0032:
- **Regra de processo incompleta:** o checador de arquitetura do ADR-0010 (`skills/org-atlas/tests/architecture_rules.py`) só pega `subprocess.run(...)` e `os.system(...)` chamados pelo nome do módulo. `from subprocess import run`, `import subprocess as sp` e `from os import system` passam pela SPEC-0032:UT-05 sem aviso. Hoje o `atlas.py` não usa nada disso, mas a regra não protege contra o caso.
- **Endurecimento sem teste:** a correção do G4 (commit 6faff6c) trouxe comportamentos verificados só à mão: erro de sistema de arquivos sem traceback (exit 1), backups `.bak`, `.bak.1`…, `init --join` recusando `--org`/`--mode`/`--force`, ERRO para `atlas` relativo e mensagem própria para profile com espaço.

## 2. Causa Raiz
Os testes da SPEC-0032 foram congelados no commit red (04e58b5), antes da revisão. O checador de processo procura só chamadas no formato `módulo.função` (`_process_call`), sem acompanhar imports com alias ou de nomes.

## 3. Mudança Proposta
- `architecture_rules.py`: a regra de processo também reporta, fora de `run_collector`, imports de nomes de `subprocess` (`from subprocess import ...`), módulos com alias (`import subprocess as x`) e `from os import system`/`popen`/`exec*`/`spawn*`.
- `tests/test_hardening.py`: testes de regressão para cada comportamento do endurecimento, pela CLI, em diretórios temporários.
- `atlas.py`: só se algum teste mostrar diferença entre o que foi verificado à mão e o comportamento real.
- **Não muda:** o contrato da SPEC-0032.

**Padrão seguido:** `skills/second-brain/tests/brain_architecture_rules.py` e os testes de CLI da SPEC-0032 (`skills/org-atlas/tests/test_config.py`).

**Rollback:** reverter o commit.

**Outras ocorrências:** a regra equivalente da `second-brain` (`brain_architecture_rules.py`) pode ter a mesma lacuna — verificar na revisão e, se tiver, abrir spec própria.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os comportamentos já existem e os testes novos são de regressão.
- **UT-01** — Dado código de exemplo com `from subprocess import run`, `import subprocess as sp` e `from os import system` fora de `run_collector`, quando a regra de processo roda, então os três são reportados; dentro de `run_collector`, nenhum.
- **IT-01** — Pela CLI: `init` em pasta sem permissão de escrita, `init` com `atlas-config.yml` que não é UTF-8 e `doctor` em pasta sem permissão saem com 1, com "erro:" ou ERRO, e sem traceback (guarda: passa antes da mudança).
- **IT-02** — Pela CLI: dois `init --force` seguidos geram `.bak` e `.bak.1` com o conteúdo certo; `init --join --mode x` sai com 2; `atlas` relativo na configuração local gera ERRO no `doctor`; profile com espaço gera a mensagem própria sem ecoar o valor (guarda: passa antes da mudança).

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PENDING | | |
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
