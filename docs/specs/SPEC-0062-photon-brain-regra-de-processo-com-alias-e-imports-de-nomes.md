---
id: SPEC-0062
title: "photon-brain: regra de processo com alias e imports de nomes"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-15
parent:
depends_on: [SPEC-0046]
consumes_contract: []
touches: [skills/photon-brain/tests/brain_architecture_rules.py, skills/photon-brain/tests/test_architecture.py, skills/photon-brain/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-16
---

# SPEC-0062 — photon-brain: regra de processo com alias e imports de nomes

## 1. Problema
A regra de processo da `photon-brain` (`skills/photon-brain/tests/brain_architecture_rules.py`, `subprocess_findings`) só pega chamadas no formato `módulo.função` (`subprocess.run(...)`, `os.system(...)`). `from subprocess import run`, `import subprocess as sp` e `from os import system` usados fora de `run_processor` passam sem aviso: um exemplo com os três dentro de `doctor()` deu `[]` (checagem feita na SPEC-0046, 2026-11-15). Hoje o código da skill não usa nada disso; a regra é que não protege contra o caso. É a mesma lacuna que a SPEC-0046 fechou na `boson-atlas`.

## 2. Causa Raiz
`_process_call` só reconhece `ast.Attribute` sobre um `ast.Name` que seja o nome do próprio módulo; não acompanha imports com alias nem imports de nomes. A regra de remoção do mesmo arquivo (`removal_findings`, com `_module_aliases`) já trata alias e `from X import` e serve de modelo.

## 3. Mudança Proposta
- `subprocess_findings` passa a reportar, fora de `run_processor`, `from subprocess import ...`, `import subprocess as x`, `from os import system`/`popen`/`exec*`/`spawn*` e as chamadas feitas pelo alias ou pelo nome importado, como a regra da `boson-atlas` depois da SPEC-0046.
- A docstring diz que a regra é por nome e não pega acesso dinâmico (`__import__`, `importlib`, `getattr`).
- **Não muda:** o código da `photon-brain`, o ADR-0009 (processos externos), o ADR-0014 nem a lista de chamadas permitidas.

**Padrão seguido:** `skills/boson-atlas/tests/architecture_rules.py` (`subprocess_findings` depois da SPEC-0046) e `removal_findings` do próprio arquivo

**Rollback:** reverter o commit

**Outras ocorrências:** Nenhuma — a `gluon-spec` e o `mcp/` têm regras próprias, a conferir na revisão

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0062:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — o `test_architecture.py` atual já fixa a regra contra o código real
- **UT-01** — Dado código de exemplo com `from subprocess import run`, `import subprocess as sp` e `from os import system` usados fora de `run_processor`, quando a regra de processo roda, então os três são reportados com `arquivo:linha`; dentro de `run_processor` nenhum, e `import os`/`from os import path` no módulo não geram achado.
- Integração/E2E: N/A — regra estática de arquitetura, provada contra exemplo e contra o código real

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 em `skills/photon-brain/tests/test_architecture.py` com a tag `SPEC-0062:UT-01`, falhando pelo motivo certo
- [x] Green: `subprocess_findings` em `skills/photon-brain/tests/brain_architecture_rules.py` acompanha alias e imports de nomes, como a `boson-atlas` depois da SPEC-0046
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4), integração + CI (G5) e H2, Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — fe3e747 | 2026-11-15 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=1)) — ab34a09 | 2026-11-16 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — c549aae | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — b10f6b1 | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (sem blocker/major; lógica igual à da boson-atlas depois da SPEC-0046; 3 minors e 3 nits como pendências). Depois da revisão só entraram o merge da main e a versão do plugin 2026.11.13 (c549aae). — 3921ee6 | 2026-11-16 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 8ef712b | 2026-11-16 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-16 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-16 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 8a1c90e | 2026-11-16 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- A regra de arquitetura da `photon-brain` que limita processos externos a `run_processor` passou a pegar `from subprocess import ...`, `import subprocess as x`, `from os import system`/`popen`/`exec*`/`spawn*` e as chamadas feitas por esses alias ou nomes, como a da `boson-atlas` depois da SPEC-0046. O código da skill não mudou e continua sem achado. Plugin 2026.11.13.

### Como foi feito
- `_is_process_name`, `_process_names`, `_process_import` e `_process_call` copiados da regra da `boson-atlas`; a docstring diz que a regra é por nome e não pega acesso dinâmico (`__import__`, `importlib`, `getattr`).
- Teste em ab34a09; correção em 8612dd2; versão do plugin em c549aae, depois do merge da SPEC-0063.
- **Revisão G4:** APPROVED na rodada 1 (lógica idêntica à da `boson-atlas`; 6 mutações pegas).

### Prova de Correção
- **Antes:** ab34a09 vermelho — `AssertionError: Lists differ: [] != [1, 2, 3, 10, 11, 12]` (nenhum achado para alias e imports de nomes).
- **Depois:** 8612dd2 verde; suíte completa em 3.9 e 3.14 e CI do PR #38.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Alias e imports de nomes de processo fora de `run_processor` reportados com `arquivo:linha`; nada dentro dela; `import os`/`from os import path` sem achado; código real sem achado | PASS | `test_architecture.py::ProcessRulesTest` — CI do PR #38 (run 43938638132, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — ab34a09 vermelho, 8612dd2 verde
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido — regra da `boson-atlas` depois da SPEC-0046
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — CHANGELOG da `photon-brain` em `[Unreleased]` (o `brain.py` e a `BRAIN_VERSION` não mudam, ADR-0007)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma: `boson-atlas` já corrigida (SPEC-0046), `mcp/` com regra própria (SPEC-0054); `gluon-spec` não restringe processos por regra de arquitetura

### Deploy
N/A — plugin 2026.11.13, PR #38.

### Pendências
- Minors da revisão, sem spec: o UT-01 não cobre alias de nome importado (`run as r`), `os.spawnlp` nem `from subprocess import a, b`; `from os import *` esconde as chamadas (mesmo furo na `boson-atlas`, candidato a spec comum às duas skills); o mapa de nomes ignora escopo (falso positivo para o lado seguro).
- Nit: import em corpo de classe rotulado como "nível de módulo".

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
