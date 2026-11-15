---
id: SPEC-0045
title: "sdd-management: teste de tempo do leak-check tolerante à carga"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-02
parent:
depends_on: []
consumes_contract: []
touches: [skills/gluon-spec/tests/test_private_mode.py, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0045 — sdd-management: teste de tempo do leak-check tolerante à carga

## 1. Problema
`SPEC-0004:IT-10` (`test_private_mode.LeakCheckCommandTest.test_fifty_commits_in_under_two_seconds`) exige que `leak-check --range` sobre 50 commits termine em menos de 2 s de relógio. Numa máquina com load average entre 5 e 13 ele levou 2,7 s, 3,0 s e 3,8 s, falhando também na `main`, sem nenhuma mudança na sdd-management. Como os comandos `test` do `sdd-config.yml` encadeiam as suítes com `&&`, essa falha derruba o `gate --run` de G1, G2 e G5 de qualquer spec e interrompe a cadeia antes das outras suítes (SPEC-0034 e SPEC-0035 tiveram o G5 registrado como manual por isso).

## 2. Causa Raiz
O teste mede tempo de relógio do processo inteiro (Python + git em subprocesso), que depende da carga da máquina, contra um limite fixo pensado para máquina ociosa.

## 3. Mudança Proposta
- O teste mede, na mesma execução e logo antes, uma linha de base com o mesmo perfil de processos do `leak-check --range`: o tempo de rodar `git show -U0 --format= <sha>` para cada um dos 50 commits do intervalo (o `leak-check` abre um `git log -1` e um `git show` por commit, então os dois crescem juntos com a carga; a razão medida fica entre 1,9 e 2,4). O limite passa a ser `max(2 s, 3 × linha de base)`: em máquina ociosa (linha de base perto de 0,3 s) fica no piso de 2 s e pega um `leak-check` cerca de 2,6× mais lento; sob carga cresce junto com a linha de base (Emenda v2). A decisão fica numa função pequena do teste (`limite(linha_de_base)`), testada à parte.
- Sem variável de ambiente: o teste se ajusta sozinho, sem configuração na CI.
- **Não muda:** o `leak-check`, a meta de desempenho da SPEC-0004.

**Padrão seguido:** os demais testes de `test_private_mode.py`.

**Rollback:** reverter o commit.

**Outras ocorrências:** procurar outros `assertLess(elapsed, …)` nas suítes (`second-brain`, `org-atlas`: o teste de 1.000 Applications da SPEC-0035) e aplicar a mesma regra se tiverem o mesmo risco.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste existente é o próprio objeto.
- **UT-01** — Dados linha de base de 1,0 s e `leak-check` de 1,5 s, linha de base de 2,0 s (carga) e `leak-check` de 3,8 s, e linha de base de 0,5 s e `leak-check` de 2,5 s, quando a regra `limite(linha_de_base)` é aplicada, então os dois primeiros passam (limites 3 s e 6 s) e o terceiro falha (limite 2 s, o piso), com o caso que falha escrito de forma explícita; e o teste real de 50 commits usa essa regra com a linha de base medida na mesma execução.
- Integração/E2E: N/A — mudança só no teste.

## 5. Questões em Aberto
- [x] Linha de base relativa ou fator por variável de ambiente? — Linha de base relativa medida na mesma execução, com piso de 2 s: não exige configuração e continua pegando regressão real (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 em `skills/gluon-spec/tests/test_private_mode.py` com a tag `SPEC-0045:UT-01`, falhando porque `limite` ainda não existe
- [x] Green: `limite(linha_de_base) = max(2 s, 3 × linha de base)` e IT-10 medindo a linha de base (`git show -U0 --format= <sha>` de cada um dos 50 commits) na mesma execução (Emenda v2); `version` do `plugin.json` sobe
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7), com as outras ocorrências de `assertLess(elapsed, …)` registradas

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (errors=1, skipped=1)) — 44296c6 | 2026-11-15 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — c47fd0d | 2026-11-15 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 3089403 | 2026-11-15 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 2; 0 falhas em 11 rodadas sob carga 2-3x núcleos; regressão 3x pega) — 9938d60 | 2026-11-15 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #28 em 6bb32cb verde (run 43682326239 ci Python 3.9/3.15, com a checagem de versão do plugin; run 43682326245 sdd/pr-check) — 6bb32cb | 2026-11-15 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-15 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-15 |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-15 | G2 | spec | SPEC_DEFECT do Reviewer (G4): a linha de base (python3 -c pass + git log, 2 processos) não tem o perfil do leak-check --range (um git show por commit, 50+ processos); a razão real é ~30x, então limite = max(2 s, 10x base) fica sempre no piso de 2 s e o IT-10 segue falhando sob carga | Implementer seguiu a spec (b9167b0); G2 --run FAIL (failures=1); Reviewer reproduziu 3 falhas sob carga: elapsed 2,26/2,19/2,22 s com base 0,055-0,063 s | thomas | Emenda v2 — linha de base com 50 git show (mesmo perfil do leak-check) e limite max(2 s, 3x base) (H1 thomas, 2026-11-15) | 2026-11-15 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
O teste de tempo do leak-check (`SPEC-0004:IT-10`) deixou de falhar quando a máquina está carregada e continua pegando lentidão real. Ele mede, na mesma execução, uma linha de base com o mesmo perfil de processos do `leak-check --range` (um `git show -U0 --format= --no-color <sha>` para cada um dos 50 commits) e aceita até `max(2 s, 3 × linha de base)`. Em máquina ociosa o limite continua 2 s (meta da SPEC-0004). O `leak-check` não mudou.

### Como foi feito
- `limite(linha_de_base)` no nível do módulo de `skills/gluon-spec/tests/test_private_mode.py`, testada à parte pelo UT-01 (`LeakCheckLimiteTest`).
- IT-10: os SHAs saem de `git rev-list` fora da medição; a linha de base roda o mesmo comando de `leak_scan` (`spec_graph.py`, ~linha 880); a mensagem do assert mostra elapsed e base.
- `version` do plugin 2026.11.2 → 2026.11.3 (regra da SPEC-0056).
- **Emenda v2 (IMP-01):** a primeira regra (linha de base `python3 -c pass` + `git log`, fator 10) seguia a spec, mas o Reviewer mostrou que ela ficava sempre no piso de 2 s e falhava sob carga; a spec foi emendada com o H1 do thomas e refeita com teste antes (6f986b1 → c47fd0d).
- **Revisão G4:** rodada 1 REPROVADO (blocker da regra), rodada 2 APPROVED.

### Prova de Correção
- **Antes:** com o limite fixo de 2 s, o IT-10 falhava sob carga (2,7 s, 3,0 s e 3,8 s com load entre 5 e 13, seção 1); a regra da v1 também (Reviewer, rodada 1: `AssertionError: 2.263854291 not less than 2.0 : elapsed=2.264s base=0.055s`, três de três). Vermelho da regra nova em 6f986b1: `AssertionError: 10.0 != 3.0`.
- **Depois (c47fd0d):** Reviewer, rodada 2, com 20 e 30 processos de carga em 10 núcleos: elapsed 2,08–2,65 s, todas acima dos 2 s antigos, e 0 falhas em 11 rodadas (limite 2,91–3,45 s). Ociosa: 0,76 s contra o piso de 2 s, e um `leak-check` 3× mais lento é reprovado (`elapsed=2.635s base=0.343s`).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `limite()` aceita 1,5 s com base 1,0 s e 3,8 s com base 2,0 s, e reprova 2,5 s com base 0,5 s | PASS | `test_private_mode.py::LeakCheckLimiteTest` — vermelho em 6f986b1, verde em c47fd0d; CI do PR #28 (run 43682326239, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — 44296c6/6f986b1 vermelhos, c47fd0d verde; IT-10 medido sob carga na revisão
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 2
- [x] Padrão existente mantido — helper no topo do módulo e docstring como tag, como o resto de `test_private_mode.py`
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — não aplicável: só teste mudou, sem comportamento da skill
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma: `test_living_docs.py:216` já usa linha de base; os de photon-brain e boson-atlas (`test_collector_argocd.py:315`, `test_scan.py:815`) têm limites de 10 s e 20 s, folgados, sem falha observada

### Deploy
N/A — branch `sdd/SPEC-0045-...`, PR #28.

### Pendências
Nenhuma nova. Riscos residuais da revisão, sem spec: folga de ~25% entre a razão medida (até 2,4) e o fator 3; um pico de carga só durante o `leak-check` ainda pode estourar o limite (não reproduzido em 11 rodadas). Melhoria de ferramenta: o `gate G4 --by` só reconhece `APPROVED`, não `APROVADO`.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-15 | Linha de base passa a ser `git show -U0 --format= <sha>` de cada um dos 50 commits (mesmo perfil do `leak-check --range`) e o limite vira `max(2 s, 3 × linha de base)`; UT-01 com valores realistas | IMP-01: com `python3 -c pass` + `git log` (2 processos) a razão real era ~30×, o limite ficava sempre no piso de 2 s e o IT-10 seguia falhando sob carga | nenhuma | thomas, 2026-11-15 |
