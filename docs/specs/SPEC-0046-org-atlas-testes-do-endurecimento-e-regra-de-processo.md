---
id: SPEC-0046
title: "org-atlas: testes do endurecimento do init e do doctor e regra de processo com alias"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-30
parent:
depends_on: [SPEC-0033]
consumes_contract: []
touches: [skills/boson-atlas/tests/architecture_rules.py, skills/boson-atlas/tests/test_architecture.py, skills/boson-atlas/tests/test_hardening.py, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/references/redaction.md, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0002]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0046 — org-atlas: testes do endurecimento do init e do doctor e regra de processo com alias

## 1. Problema
Duas pendências da revisão (G4) da SPEC-0032:
- **Regra de processo incompleta:** o checador de arquitetura do ADR-0010 (`skills/boson-atlas/tests/architecture_rules.py`) só pega `subprocess.run(...)` e `os.system(...)` chamados pelo nome do módulo. `from subprocess import run`, `import subprocess as sp` e `from os import system` passam pela SPEC-0032:UT-05 sem aviso. Hoje o `atlas.py` não usa nada disso, mas a regra não protege contra o caso.
- **Pendências da revisão da SPEC-0033 (minor):** a regra de chave proibida tem ruído nos dois sentidos (descarta `monkey`, `primary_key`, `sort_keys`, `tokenizer`, `public_key`; não pega `auth`) e o `scan` não confere se `collector` e `category` da saída batem com o id e a categoria configurados.
- **Pendência da revisão da SPEC-0034 (G4, minor 7):** a SPEC-0034 pede o teste de arquitetura estendido aos coletores ("`subprocess` só para o executável do provedor", sem shell), mas `test_architecture.py` ficou fora do `touches` dela; hoje só a regra de biblioteca padrão cobre `assets/collectors/`.
- **Endurecimento sem teste:** a correção do G4 (commit 6faff6c) trouxe comportamentos verificados só à mão: erro de sistema de arquivos sem traceback (exit 1), backups `.bak`, `.bak.1`…, `init --join` recusando `--org`/`--mode`/`--force`, ERRO para `atlas` relativo e mensagem própria para profile com espaço.

## 2. Causa Raiz
Os testes da SPEC-0032 foram congelados no commit red (04e58b5), antes da revisão. O checador de processo procura só chamadas no formato `módulo.função` (`_process_call`), sem acompanhar imports com alias ou de nomes.

## 3. Mudança Proposta
- `architecture_rules.py`: a regra de processo também reporta, fora de `run_collector`, imports de nomes de `subprocess` (`from subprocess import ...`), módulos com alias (`import subprocess as x`) e `from os import system`/`popen`/`exec*`/`spawn*`.
- `architecture_rules.py`/`test_architecture.py`: em `assets/collectors/*.py`, `subprocess` só dentro da função que chama o executável do provedor (`run_gh` no `github.py`), sempre com lista de argumentos e sem `shell=True`; `os.system`/`popen` proibidos.
- `tests/test_hardening.py`: testes de regressão para cada comportamento do endurecimento, pela CLI, em diretórios temporários.
- `atlas.py`: só se algum teste mostrar diferença entre o que foi verificado à mão e o comportamento real; afinar a regra de chave proibida; ``category` diferente da declarada na configuração vira violação (mudança aditiva no contrato `org-atlas/collector@1`); `collector` diferente do id declarado continua aceito, porque um coletor reutilizável (o `generic` da SPEC-0034) imprime o próprio nome e é declarado com ids diferentes — o snapshot é sempre gravado pelo id declarado, e o contrato passa a dizer isso (Emenda v2).
- **Não muda:** o contrato da SPEC-0032.

**Padrão seguido:** `skills/photon-brain/tests/brain_architecture_rules.py` e os testes de CLI da SPEC-0032 (`skills/boson-atlas/tests/test_config.py`).

**Rollback:** reverter o commit.

**Outras ocorrências:** a regra equivalente da `second-brain` (`brain_architecture_rules.py`) pode ter a mesma lacuna — verificar na revisão e, se tiver, abrir spec própria.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os comportamentos já existem e os testes novos são de regressão.
- **UT-01** — Dado código de exemplo com `from subprocess import run`, `import subprocess as sp` e `from os import system` fora de `run_collector`, quando a regra de processo roda, então os três são reportados; dentro de `run_collector`, nenhum.
- **UT-04** — Dado um coletor de exemplo em `assets/collectors/` com `subprocess.run` fora da função do provedor, ou com `shell=True`, quando a regra de arquitetura roda, então ele é reportado; o `github.py` real não gera achado.
- **IT-01** — Pela CLI: `init` em pasta sem permissão de escrita, `init` com `atlas-config.yml` que não é UTF-8 e `doctor` em pasta sem permissão saem com 1, com "erro:" ou ERRO, e sem traceback (guarda: passa antes da mudança).
- **UT-02** — Dado chaves `monkey`, `primary_key`, `sort_keys`, `tokenizer`, `public_key` e `auth`, quando a regra de chave proibida roda, então só `auth` é descartada.
- **UT-03** — Dado uma saída com `category` diferente da declarada no `atlas-config.yml`, quando o `scan` valida, então há violação e o snapshot não é gravado; dada uma saída com `collector` diferente do id declarado (como o `generic` declarado como `db-facts`) e `category` igual, então o `scan` aceita e grava o snapshot pelo id declarado (Emenda v2).
- **IT-02** — Pela CLI: dois `init --force` seguidos geram `.bak` e `.bak.1` com o conteúdo certo; `init --join --mode x` sai com 2; `atlas` relativo na configuração local gera ERRO no `doctor`; profile com espaço gera a mensagem própria sem ecoar o valor (guarda: passa antes da mudança).

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 a UT-04 com a tag `SPEC-0046:<ID>`, falhando pelo motivo certo; IT-01 e IT-02 (guardas) passando já antes da mudança
- [x] Green: regra de processo com alias e imports de nomes; regra dos coletores; chave proibida afinada; `category` conferida no `scan` (Emenda v2); `collector-contract.md`, `redaction.md`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7), com a verificação da regra equivalente da photon-brain

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=20, skipped=1)) — b0487de | 2026-11-15 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 0dd13d6 | 2026-11-15 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 6ee82b1 | 2026-11-15 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 3, delta 0dd13d6; minor: pai sem listagem ainda difere entre versões) — 0dd2b93 | 2026-11-15 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #29 em 8c9801d verde (run 43690116091 ci Python 3.9/3.15; run 43690116095 sdd/pr-check) — 8c9801d | 2026-11-15 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-15 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 29c9ac3 | 2026-11-15 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-15 | G2 | spec | SPEC_DEFECT do Implementer: o UT-03 exige collector da saída igual ao id declarado, mas o coletor generic (SPEC-0034) imprime sempre collector: generic por contrato (generic.md, test_collector_generic.py) e é declarado com outros ids (db-facts, facts); a conferência quebra 19 testes de test_build, test_context e test_lint | Implementer ligou identity_violations no scan_one: UT-01 a UT-04, IT-01 e IT-02 verdes, 19 falhas só do generic; trabalho guardado em git stash | thomas | Emenda v2 — scan confere só category; collector diferente do id aceito (generic), snapshot pelo id declarado (thomas, piloto automático, 2026-11-15) | 2026-11-15 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- **Regra de processo (ADR-0010):** `architecture_rules.py` pega também `from subprocess import ...`, `import subprocess as x`, `from os import system|popen|exec*|spawn*` e as chamadas pelo alias ou pelo nome importado fora de `run_collector`.
- **Regra dos coletores:** em `assets/collectors/`, processo só na função do provedor (`run_gh` no `github.py`, `run_cli` no `argocd.py`), com lista de argumentos, sem `shell=True` e sem `**kwargs` desempacotados; `os.system`/`popen`/`exec*`/`spawn*` proibidos.
- **Chave proibida afinada (`is_forbidden_key`):** passa a descartar `auth`/`authorization`; deixa de descartar `monkey`, `primary_key`, `sort_keys`, `tokenizer`, `public_key` e qualificadores de chave de dados; nomes colados terminados em `key` (`privkey`, `hmackey`, `accountkey`...) continuam descartados.
- **`scan`:** `category` diferente da declarada é violação e o snapshot não é gravado; `collector` diferente do id declarado é aceito e o snapshot vai pelo id declarado (Emenda v2).
- **Atlas sem permissão de leitura:** `doctor`, `init`, `init --join`, `scan`, `lint` e `config` acusam "sem permissão de leitura" com exit 1, em qualquer versão do Python (antes o 3.14+ dizia "não existe").
- `ATLAS_VERSION` e `version` do plugin 2026.11.4; `collector-contract.md`, `redaction.md` e CHANGELOG da `boson-atlas`.

### Como foi feito
- Testes em b0487de, 256317b (Emenda v2), c0f1b78 (lint) e 9bb1f74 (regressão da revisão), em `skills/boson-atlas/tests/test_architecture.py` e no novo `test_hardening.py`; correções em c79473e, 22f25c4 e 0dd13d6.
- **IMP-01 / Emenda v2:** o coletor `generic` (SPEC-0034) imprime `collector: generic` e é declarado com outros ids; a conferência estrita de `collector` quebrava 19 testes, então só a `category` é conferida.
- **Revisão G4:** rodada 1 REPROVADO (major: a lista fechada de finais deixava vazar chaves coladas como `privkey`); rodada 2 APPROVED; rodada 3 APPROVED do delta 0dd13d6, que corrigiu a falha do IT-01 no Python 3.15 da CI.

### Prova de Correção
- **Antes:** b0487de vermelho (20 falhas: UT-01 `0 != 3`, UT-04 `collector_process_findings não existe`, UT-02 `auth é chave proibida`, UT-03 `0 != 1`); 9bb1f74 vermelho (12 nomes colados dados como permitidos e `**opts` sem achado); IT-01 vermelho no Python 3.15 da CI (`OK pasta do atlas` + `atlas-config.yml — não existe`).
- **Depois (0dd13d6):** suíte completa verde (boson-atlas 354 testes, 1 skip antigo) no 3.9 e no 3.14 locais e no 3.9/3.15 da CI.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Regra de processo reporta alias e imports de nomes fora de `run_collector` | PASS | `test_architecture.py` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | Chave proibida afinada, com nomes colados terminados em `key` descartados | PASS | `test_hardening.py::ForbiddenKeyTest` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | `category` diferente é violação; `collector` diferente aceito, snapshot pelo id declarado | PASS | `test_hardening.py` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Regra dos coletores: processo só na função do provedor, lista, sem shell e sem `**kwargs` | PASS | `test_architecture.py::CollectorProcessRulesTest` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Erro de sistema de arquivos sai com 1 e sem traceback (pasta sem escrita, config não UTF-8, atlas sem permissão) | PASS | `test_hardening.py::FileSystemErrorTest` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |
| IT-02 | `.bak`/`.bak.1`, `init --join` recusando opções, `atlas` relativo e profile com espaço | PASS | `test_hardening.py::InitHardeningTest` — CI do PR #29 (run 43690116091, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — b0487de/9bb1f74 vermelhos, 0dd13d6 verde; IT-01 vermelho no 3.15 antes de 0dd13d6
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodadas 2 e 3
- [x] Padrão existente mantido — checadores por AST como `brain_architecture_rules.py`; testes de CLI com `Sandbox`
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `collector-contract.md`, `redaction.md`, CHANGELOG `[2026.11.4]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — SPEC-0062 (mesma lacuna de alias na `photon-brain`)

### Deploy
N/A — `ATLAS_VERSION` 2026.11.4, PR #29.

### Pendências
- SPEC-0062 (proposed): regra de processo da `photon-brain` com alias.
- Minors da revisão, sem spec: `token` colado no início (`tokenvalue`) deixou de ser descartado; pasta pai do atlas sem listagem ainda dá "não existe" no Python 3.14+; `os.access` redundante com o `scandir`; concordância da mensagem de `OSError` genérico.
- Ferramenta: o título gerado por `spec_graph.py pr` passou do `pr_title_max` (101 > 100).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-15 | O `scan` confere só a `category` contra a declaração; `collector` diferente do id declarado continua aceito e o contrato documenta que o snapshot vai pelo id declarado; UT-03 ajustado | IMP-01: o coletor `generic` (SPEC-0034) imprime `collector: generic` por contrato e é declarado com outros ids; a conferência estrita quebrava 19 testes | nenhuma (SPEC-0034 inalterada) | thomas, 2026-11-15 (piloto automático com o recomendado) |
