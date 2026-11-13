---
id: SPEC-0056
title: "fermion: versão do plugin sobe quando as skills mudam"
tier: lite
type: feature
user_facing: false
status: implemented
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0053]
consumes_contract: []
touches: [tests/plugin/**, .github/workflows/ci.yml, .claude-plugin/plugin.json, README.md, AGENTS.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0056 — fermion: versão do plugin sobe quando as skills mudam

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O `.claude-plugin/plugin.json` fixa `version` (SPEC-0053). Com a versão explícita, o Claude Code usa a versão como chave do cache e para decidir se há atualização. Um commit novo na `main` que muda `skills/**` sem subir a versão não chega a quem roda `claude plugin update fermion@fermion-lab`. Achado M1 da revisão G4 da SPEC-0053, segundo a documentação de plugins; não foi testado na prática.

## 2. Causa Raiz
Nada liga a versão do plugin às mudanças das skills. Cada skill sobe a própria versão (`SDD_TOOL_VERSION`, `BRAIN_VERSION`, `ATLAS_VERSION`), mas o `plugin.json` fica igual.

## 3. Mudança Proposta
Checagem na CI e no `pr-check`: um PR que muda `skills/**` também muda `version` no `plugin.json` (`AAAA.MM.N` maior que o da base). README e AGENTS.md dizem quando subir. O `plugin.json` ganha `author: {"name": "thomasravache"}` (sem e-mail), que tira o aviso do `claude plugin validate` (nit N1 da revisão G4 da SPEC-0053). Avaliar `claude plugin tag` na pesquisa.

**Não muda:** o formato da versão nem as versões das skills.

**Padrão seguido:** testes em `tests/plugin/` (SPEC-0053) e passo da CI existente.

**Rollback:** reverter o commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste novo cobre a regra.
- **UT-01** — Dado um diff que muda `skills/**` sem mudar a versão do `plugin.json`, quando a checagem roda, então acusa; com a versão maior, não acusa; sem mudança em `skills/**`, não exige nada.
- **UT-02** — Dado o `plugin.json` do repositório, quando é lido, então tem `author.name` igual ao `owner.name` do marketplace e nenhum e-mail.
- **IT-01** — Dado um repositório git temporário com dois commits, quando a checagem roda contra a base, então dá o mesmo resultado do UT-01.

## 5. Questões em Aberto
- [x] A checagem fica na CI do repositório (script em `tests/plugin/`) ou vira regra do `pr-check` da `gluon-spec`? — Na CI do repositório, em `tests/plugin/`: a regra é deste repositório (o `plugin.json` só existe aqui), e o `pr-check` da `gluon-spec` serve qualquer projeto (thomas, com o recomendado, 2026-11-13)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01, UT-02 e IT-01 em `tests/plugin/` com a tag `SPEC-0056:<ID>`, falhando pelo motivo certo
- [x] Green: checagem de versão do plugin, `author` no `plugin.json`, versão 2026.11.2, passo na CI, README e AGENTS.md
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dcc2a23 (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=3)); nota: vermelho em ab0933c: test_plugin_version.py 3 testes, 3 falhas (check_plugin_version.py inexistente; plugin.json sem author) — ab0933c | 2026-11-13 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — ea20c65 | 2026-11-13 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — ea20c65 | 2026-11-13 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (a0cfe62): APPROVED — comparação AAAA.MM.N como tupla, diff base...HEAD, sem shell, author sem e-mail, docs fora do bloco sdd; minor (base fixa em origin/main) e nits (JSON inválido com traceback, base fora do formato sem aviso) corrigidos como sugerido em 630400f (testes) e d82164a; regra mantida para testes e CHANGELOG das skills (recomendação do Reviewer) — d82164a | 2026-11-13 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #26 em af7d6ba verde (run 43470182944 ci Python 3.9/3.15, com a checagem de versão do plugin; run 43470205446 sdd/pr-check) — af7d6ba | 2026-11-13 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-13 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-13 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 31b8e85 | 2026-11-13 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
Um PR que muda `skills/**` sem subir a `version` do `.claude-plugin/plugin.json` (`AAAA.MM.N`, comparada como tupla) é reprovado pela CI, com a versão da base e da HEAD na mensagem; assim `claude plugin update` sempre traz as mudanças. O `plugin.json` ganhou `author: {"name": "thomasravache"}` (sem e-mail, o aviso do `claude plugin validate` sumiu) e foi para a versão 2026.11.2. README e `AGENTS.md` explicam a regra.

### Como foi feito
- `tests/plugin/check_plugin_version.py` (stdlib): `version_findings` e a CLI `--base <ref>` (diff `base...HEAD`, versão da base por `git show`); `plugin.json` inválido vira achado legível e versão da base fora do formato vira aviso. Passo na CI só em `pull_request`, com `--base "origin/$BASE_REF"` e `fetch-depth: 0`.
- Testes em ab0933c e 630400f; implementação em a0cfe62 e d82164a.
- **Revisão G4:** APPROVED; o minor (base fixa em `origin/main`) e os nits (traceback com JSON inválido, base fora do formato sem aviso) foram corrigidos. A regra continua valendo para testes e CHANGELOG das skills, que também vão para o cache do plugin (recomendação do Reviewer).

### Prova de Correção
N/A — `type: feature`.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Mudança em `skills/**` exige versão maior; fora de `skills/**` nada é exigido | PASS | `test_plugin_version.py::VersionFindingsTest` — CI do PR #26 em af7d6ba (run 43470182944, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | `author.name` igual ao `owner.name` do marketplace, sem e-mail | PASS | `PluginAuthorTest` — CI do PR #26 em af7d6ba (run 43470182944, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Repositório git com dois commits: exit 1 sem subir a versão, 0 com versão maior ou sem mudar skills; JSON inválido e base fora do formato | PASS | `CheckAgainstBaseTest` — CI do PR #26 em af7d6ba (run 43470182944, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — N/A para feature; testes vermelhos em ab0933c e 630400f, verdes em a0cfe62 e d82164a
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido — testes em `tests/plugin/` como na SPEC-0053
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — README e `AGENTS.md`; sem CHANGELOG raiz no repositório
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma

### Deploy
N/A — plugin `fermion` 2026.11.2 na branch `sdd/SPEC-0056`, PR #26.

### Pendências
Nenhuma.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
