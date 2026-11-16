---
id: SPEC-0068
title: "gluon-spec: hook do leak-check acha a ferramenta depois de update do plugin ou remoção da cópia"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-16
parent:
depends_on: []
consumes_contract: []
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/assets/hooks/pre-push-leak, skills/gluon-spec/tests/**, skills/gluon-spec/references/private-mode.md, skills/gluon-spec/CHANGELOG.md, tools/sdd/spec_graph.py, .claude-plugin/plugin.json, scripts/fermion_doctor.py, tests/plugin/**]
adrs: [ADR-0019]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-16
---

# SPEC-0068 — gluon-spec: hook do leak-check acha a ferramenta depois de update do plugin ou remoção da cópia

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Os repositórios em modo privado têm um `pre-push` do leak-check que grava o caminho absoluto da ferramenta no momento do `private init`. Nesta máquina (2026-11-16), 16 repositórios de trabalho gravaram `~/.claude/skills/sdd-management/scripts/spec_graph.py`, a cópia antiga com o nome velho. Ao apagar essa cópia (o passo recomendado para usar o plugin `fermion`), o hook antigo chama um arquivo que não existe e todo push é recusado com a mensagem enganosa "marcas do SDD encontradas"; o único escape é `--no-verify`, que pula a proteção. O hook atual (SPEC-0057) já procura a ferramenta, mas grava `Path(__file__)`: instalado pelo plugin, esse caminho fica na pasta versionada do cache do Claude Code e quebra a cada `claude plugin update`. E o `private init` não regrava um hook que já existe.

## 2. Causa Raiz
`install_leak_hook` (`skills/gluon-spec/scripts/spec_graph.py`) grava `str(Path(__file__).resolve())` em `__SDD_TOOL__`, e o template `assets/hooks/pre-push-leak` só tem esse caminho e o `tools/sdd/` não rastreado como opções; nenhum comando atualiza hooks já instalados.

## 3. Mudança Proposta
- O hook procura a ferramenta, na ordem: o caminho gravado (se existir); a `gluon-spec` do plugin `fermion` instalado, lida de `$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json` (senão `~/.claude/plugins/…`); as cópias de skill do usuário (`gluon-spec`, depois a antiga `sdd-management`); e o `tools/sdd/` não rastreado. Sem nenhuma, a mensagem diz que a ferramenta não foi encontrada (nunca "marcas do SDD encontradas").
- `private hooks --refresh` (no repositório atual; com `--scan PASTA`, em todo repositório git sob a pasta cujo remoto ou caminho está no registro como privado) regrava só os hooks que o próprio SDD instalou (reconhecidos pelo cabeçalho), nunca um hook de outra origem, mostrando o que mudou.
- O `fermion_doctor` (SPEC-0061) e o `private status` acusam hook do leak-check que aponta para ferramenta inexistente, com o comando de atualização (só avisa, ADR-0019).
- **Não muda:** o que o leak-check procura, o escape `--no-verify` do git, hooks de gerenciadores do time (`core.hooksPath`, husky, lefthook).
**Padrão seguido:** busca da ferramenta do template atual (SPEC-0057); leitura só de arquivos e aviso com comando do `fermion_doctor` (SPEC-0061, ADR-0019)

**Rollback:** reverter o commit; hooks regravados continuam funcionando com a ferramenta gravada

**Outras ocorrências:** os hooks `commit-msg` e `pre-commit` do `vendor --hooks` usam `tools/sdd/` versionado e não dependem do caminho da skill — a conferir na revisão

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0068:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- **CH-01** — Dado um repositório temporário em modo privado com o hook instalado pela versão atual, quando o push tem marca do SDD, então o hook recusa como hoje (comportamento preservado).
- **UT-01** — Dados um hook com caminho gravado inexistente e, em pastas temporárias, um `installed_plugins.json` apontando para uma cópia do plugin, quando o hook roda, então usa a `gluon-spec` do plugin; sem plugin e com só a cópia de skill do usuário, usa a cópia; sem nenhuma, a mensagem diz "ferramenta do leak-check não encontrada" e não "marcas do SDD encontradas".
- **UT-02** — Dados um hook antigo instalado pelo SDD (cabeçalho reconhecido) e um hook `pre-push` de outra origem, quando `private hooks --refresh` roda, então só o do SDD é regravado com o template atual e o outro fica igual.
- **IT-01** — Dado um repositório real em modo privado com o hook antigo que aponta para uma cópia apagada, quando `private hooks --refresh` roda e depois `git push` para um remoto local com uma marca do SDD, então o push é recusado pelo leak-check (e sem marca, aceito).

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Fase 1 (test-writer): CH-01, UT-01, UT-02, IT-01 em `skills/gluon-spec/tests/test_private_mode.py` e o aviso do doctor em `tests/plugin/test_fermion_doctor.py`, com `CLAUDE_CONFIG_DIR`/`HOME` temporários — commit `test(...)` vermelho
- [ ] Fase 2 (implementer): busca no template `pre-push-leak`, `private hooks --refresh [--scan]`, aviso em `private status` e check `broken-leak-hook` no `fermion_doctor`; `tools/sdd/` vendorizado, CHANGELOG, `references/private-mode.md`, versão do plugin
- [ ] Fase 3 (reviewer): G4 independente
- [ ] Depois do merge: `private hooks --refresh --scan ~/dev/repos` nesta máquina (com o ok do thomas)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c0ee531 | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=10, skipped=1)) — 89c9b6c | 2026-11-16 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — dd1eabe | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — cc78d15 | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (2ª rodada; achados 1–5 resolvidos; 1 minor: --scan não lista hooks órfãos de private off — coberto à mão no passo pós-merge; 3 nits) — 8e36546 | 2026-11-16 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 9684fb9 | 2026-11-16 |
| H2 Integração aprovada | PASS | aprovado por política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS; CI do PR #41 verde (ci 3.9/3.15 e sdd) | 2026-11-16 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-16 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 08d9d6a | 2026-11-16 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- O `pre-push` do leak-check do modo privado acha a ferramenta sozinho: caminho gravado → `gluon-spec` do plugin `fermion` (`installed_plugins.json` em `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`) → cópia de skill do usuário (`gluon-spec`, depois o nome antigo) → `tools/sdd/` não rastreado. Sem ferramenta, diz "ferramenta do leak-check não encontrada"; "marcas do SDD encontradas" só quando o leak-check sai 1; outro código vira "falha ao rodar o leak-check (exit N)"; interpretador gravado ausente cai para `python3` do PATH.
- `private hooks [--refresh] [--scan PASTA]`: relatório, regravação só de hooks do SDD (inclusive o órfão de `private off` e com marcador de gerenciador do time; hook de outra origem nunca) e varredura dos repositórios registrados como privados.
- `private status` e o `fermion_doctor` (check `broken-leak-hook`, só leitura, índice git v2/v3 lido por entradas) avisam hook do SDD sem ferramenta, com o comando de conserto.
- gluon-spec 2026.11.5, plugin 2026.11.14.

### Como foi feito
- Template `assets/hooks/pre-push-leak` com `find_tool` POSIX; `render_leak_hook`/`write_leak_hook` compartilhados por `private init` e `--refresh` (recusam caminho com `"`, `$` ou crase); `find_leak_tool` em Python com a mesma ordem; `tools/sdd/` vendorizado idêntico.
- Testes em 89c9b6c e 5a66070 (emenda v3); correções em 4c57505 e dd1eabe; isolamento de subteste em 1f1eefc (TEST_DEFECT).
- **Revisão G4:** rodada 1 CHANGES_REQUESTED (hook órfão de `private off` sem conserto, marcador de time, interpretador ausente, índice v4) → Emenda v3; rodada 2 APPROVED com experimentos repetidos contra o HEAD.

### Prova de Correção
- **Antes:** 89c9b6c vermelho — o hook dizia "ferramenta do leak-check não encontrada" sem procurar o plugin/cópia e `private hooks` não existia (10 falhas); 5a66070 vermelho para os casos da emenda v3 (7 + 2 falhas).
- **Depois:** 4c57505/dd1eabe verdes; suíte completa no G5 (9684fb9) e CI do PR #41 (Python 3.9 e 3.15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Hook instalado por `private init` recusa push com marca e aceita sem | PASS | `test_private_mode.py::LeakHookToolLookupTest` — CI do PR #41 e suíte local no G5 |
| UT-01 | Busca: plugin (lista/objeto), cópia de skill (nome novo e antigo, `$HOME/.claude`), nenhuma → "não encontrada"; `python3` do PATH; exit ≠ 1 não vira "marcas"; caminho inseguro recusado; aviso no `private status` | PASS | `test_private_mode.py::LeakHookToolLookupTest` e `LeakHookAmendmentV3Test` — CI do PR #41 |
| UT-02 | `--refresh` regrava só hook do SDD (inclusive órfão e com marcador de time); hook de outra origem intacto; `--scan` só nos registrados | PASS | `test_private_mode.py::LeakHookToolLookupTest` e `LeakHookAmendmentV3Test` — CI do PR #41 |
| IT-01 | Repo real com hook apontando para cópia apagada: depois do `--refresh`, push com marca recusado e sem marca aceito | PASS | `test_private_mode.py::LeakHookToolLookupTest` — CI do PR #41 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — 89c9b6c/5a66070 vermelhos, 4c57505/dd1eabe verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido — busca da SPEC-0057; doctor só lê e só avisa (SPEC-0061, ADR-0019)
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — CHANGELOG da gluon-spec 2026.11.5 e `references/private-mode.md`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma: `commit-msg` e `pre-commit` usam `tools/sdd/` versionado (conferido na revisão)

### Deploy
N/A — plugin 2026.11.14, PR #41.

### Pendências
- Minor da revisão: `--refresh --scan` não lista hooks órfãos de repositórios que saíram do modo privado; coberto à mão no passo pós-merge nesta máquina.
- Nits: `private hooks` sem `--refresh` termina em traceback com caminho inseguro; exceção não tratada na ferramenta sai 1 e vira "marcas"; concordância "do ferramenta" em `leak_hook_problem`.
- `spec_graph.py pr --title` gerou título com 112 caracteres (o `pr-check` limita a 100); ajustado à mão no PR.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v2 | 2026-11-16 | `touches` ganha `scripts/fermion_doctor.py` e `tests/plugin/**`; o refresh vira `private hooks --refresh` no repositório atual ou `--scan PASTA`, no lugar de "todos os repositórios do registro" | o aviso do doctor mora fora da skill; o registro guarda o remoto normalizado, não a pasta, então só uma varredura acha os repositórios | nenhuma | thomas, 2026-11-16 (piloto automático com o recomendado) |
| v3 | 2026-11-16 | `private hooks --refresh` no repositório atual também regrava hook do SDD (cabeçalho reconhecido) fora do modo privado (hook órfão de `private off`); hook do próprio SDD é regravado mesmo com marcador de gerenciador do time (só hook de outra origem bloqueia); o hook cai para `python3` do PATH quando o interpretador gravado não é executável e só diz "marcas do SDD encontradas" quando o leak-check sai 1 (outro código: "falha ao rodar o leak-check (exit N)"); o doctor só aceita `tools/sdd/` não rastreado lendo índice v2/v3 com o nome ancorado na entrada (v4, ilegível ou grande: não aceita); `render_leak_hook` recusa caminho com `"`, `$` ou crase; `--scan` não visita submódulos (documentado) | G4 da SPEC-0068 (CHANGES_REQUESTED): o comando recomendado não resolvia esses casos | nenhuma | thomas, 2026-11-16 (piloto automático com o recomendado) |
