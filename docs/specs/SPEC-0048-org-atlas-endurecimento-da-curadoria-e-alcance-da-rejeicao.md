---
id: SPEC-0048
title: "org-atlas: endurecimento da curadoria, do context e do lint, e alcance da rejeição"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-02
parent:
depends_on: [SPEC-0037, SPEC-0038, SPEC-0039, SPEC-0040]
consumes_contract: []
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/test_curate.py, skills/boson-atlas/tests/test_context.py, skills/boson-atlas/tests/test_lint.py, skills/boson-atlas/tests/test_vendor.py, skills/boson-atlas/references/modes.md, skills/boson-atlas/references/maintenance.md, skills/boson-atlas/references/context.md, skills/boson-atlas/references/curation.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0012]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0048 — org-atlas: endurecimento da curadoria, do context e do lint, e alcance da rejeição

## 1. Problema
Pendências da revisão G4 da SPEC-0037 (todas menores, nenhuma quebra a garantia do ADR-0012):
- Nome de repositório ou padrão vindo de um coletor próprio com `<!-- atlas:end evidence -->` faz o arquivo da convenção crescer a cada `propose` (texto solto fora da região).
- Uma rejeição só bloqueia o mesmo id: rejeitada `pr-title-conventional` (organization), uma mudança de maioria propõe `pr-title-conventional-acme-r0` (mesmo kind e padrão, outro escopo).
- Ids de convenção podem colidir (`acme/a-b` × `acme-a/b`; `Acme/API` × `acme/api`): duas propostas escrevem o mesmo arquivo.
- `--via` aceita dígitos não ASCII (`PR #３`).
- Pendências da revisão G4 da SPEC-0039 (menores; dependem de um `extra_patterns` montado para isso): o `path` dos achados do `lint` é mascarado só por componente, então um padrão que atravessa `/` (`vault/[a-z0-9]{8}`, ou com lookbehind) aparece no texto; nomes com vários pontos (`x.tar.gz`) e arquivos ocultos (`.acme-…`) não têm o radical testado; destinos de link com `#fragmento` ou `?query` são mascarados como estão escritos.
- Pendência da revisão G4 da SPEC-0038 (menor): no pacote do `context`, o nome do serviço entra num título `### {nome}`; um serviço chamado `## Convenções (regra)` vira `### ## Convenções (regra) (…)`, um título de nível 3 que imita uma seção. Crase num valor também escapa do código inline (só na própria linha, sem criar estrutura).
- Pendência da revisão G4 da SPEC-0040 (menor): quando a skill instalada difere da cópia vendorizada em `.org-atlas/skill/scripts/atlas.py`, o `lint` rodado pela skill instalada acusa ERRO `secret-leak` falso nessa cópia (as regex da própria ferramenta), com a sugestão "troque a credencial".

## 2. Causa Raiz
`_clean_line` só é aplicado aos títulos da amostra; `_id_part` não é injetivo; a regra "rejeitada nunca volta" compara só o id; o padrão de `--via` usa `\d`.

## 3. Mudança Proposta
- `repo` e `pattern` passam por `_clean_line` na evidência.
- Ids por repositório ganham sufixo curto estável (hash do `<org>/<nome>`) quando dois repositórios caem no mesmo id.
- `--via` com `[0-9]+`.
- No `lint`, depois da máscara por componente, o caminho inteiro também passa por `_mask_all`; o radical é testado também até o primeiro ponto; destinos de link são mascarados sem `#`/`?` e o sufixo volta depois.
- No `context`, o nome do serviço no título vai entre crases (ou com `#` inicial escapado) e crases dentro de valores são neutralizadas.
- No `lint`, a cópia da ferramenta em `.org-atlas/skill/scripts/atlas.py` que difere da skill instalada vira AVISO `config` ("cópia da skill desatualizada — rode `vendor`") em vez de `secret-leak`.
- Uma rejeição vale para o mesmo kind e padrão em qualquer escopo: rejeitada a convenção da organização, o `propose` não propõe a mesma regra para um repositório (nem o contrário). A linha da rejeição passa a ser comparada por `(kind, pattern)` além do id.
- **Não muda:** o formato do arquivo de convenção nem quem pode confirmar ou rejeitar.

**Padrão seguido:** `slug` com hash da SPEC-0036 (nomes de página longos ou colidentes).

**Rollback:** reverter o commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_curate.py` cobre o comportamento atual.
- **UT-01** — Dado um repositório com `<!-- atlas:end evidence -->` no nome, quando `propose` roda quatro vezes, então o arquivo tem o mesmo tamanho e uma região só.
- **UT-02** — Dado `acme/a-b` e `acme-a/b` com o mesmo padrão dominante só no repositório, quando as propostas são calculadas, então há dois ids diferentes e dois arquivos.
- **UT-03** — Dado `--via "PR #３"`, quando `confirm` valida, então sai com 2.
- **UT-05** — Dado `extra_patterns: ['vault/[a-z0-9]{8}']` e um arquivo `vault/abcd1234.bin` não UTF-8, `acme-bbbbcccc.tar.gz` com `^acme-[0-9a-f]{8}$` e um link para `acme-eeee1111#sec`, quando o `lint` roda, então nenhum desses valores aparece na saída, em texto ou `--json`.
- **UT-04** — Dado um serviço chamado `## Convenções (regra)`, quando o `context` monta o pacote, então nenhuma linha do Markdown, de qualquer nível de título, tem como texto um título fixo das seções.
- **UT-06** — Dado um atlas vendorizado cuja `.org-atlas/skill/scripts/atlas.py` difere da skill instalada (sem segredo nela), quando o `lint` roda pela skill instalada, então não há ERRO `secret-leak` nesse arquivo e há AVISO `config` sugerindo `vendor`; um segredo plantado em outro arquivo da cópia continua ERRO.
- **UT-07** — Dadas rejeições `(kind: pr-title, pattern: conventional)` no escopo organization, quando a regra de rejeição compara candidatas `(pr-title, conventional)` em escopo de repositório e `(pr-title, ticket-prefix)` no da organização, então a primeira é bloqueada e a segunda não.
- **IT-01** — Dado `pr-title-conventional` rejeitada no escopo organization, quando a maioria muda e só um repositório segue o padrão, então nenhuma proposta `pr-title-conventional-<repo>` é criada e o `curate list` mostra só a rejeitada; um padrão diferente do mesmo kind continua sendo proposto.

## 5. Questões em Aberto
- [x] Uma rejeição vale para o kind+padrão em qualquer escopo (não propõe `pr-title-conventional-<repo>` depois de rejeitar a da organização) ou só para o mesmo id, como hoje? — Para o kind+padrão em qualquer escopo: quem rejeita a regra rejeita a regra, não o escopo; é a leitura de "rejeitada nunca volta" do ADR-0012 (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 a UT-07 e IT-01 com a tag `SPEC-0048:<ID>`, falhando pelo motivo certo
- [x] Green: evidência com `_clean_line`, ids sem colisão, `--via` ASCII, máscara do `lint` (caminho, radical, links), títulos do `context`, cópia vendorizada como AVISO `config`, rejeição por `(kind, pattern)`; docs em `references/`, CHANGELOG da boson-atlas, `ATLAS_VERSION` e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=19, skipped=1)) — da4c65f | 2026-11-15 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — ce53b6c | 2026-11-15 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1426398 | 2026-11-15 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 2; cópia desatualizada volta a ser varrida) — 49abb02 | 2026-11-15 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #31 em c264257 verde (run 43699264213 ci Python 3.9/3.15; run 43699264204 sdd/pr-check) — c264257 | 2026-11-15 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-15 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 217e20a | 2026-11-15 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- **Curadoria:** o nome do repositório e o padrão vindos de coletor passam por `_clean_line` na evidência e nos títulos (o arquivo não cresce mais a cada `propose`); ids por repositório que colidem (`acme/a-b` × `acme-a/b`) ganham sufixo curto do hash de `<org>/<nome>`; `--via` só com dígitos ASCII (`^(PR #[0-9]+|local)\Z`).
- **Rejeição por regra:** `is_rejected` compara `(kind, pattern)` em qualquer escopo além do id; rejeitada a convenção da organização, o `propose` não propõe a mesma regra para um repositório, nem o contrário. O padrão de uma rejeitada é derivado do id (com a linha `- Padrão:` da evidência como reserva).
- **`lint`:** o caminho inteiro também passa por `_mask_all`, o radical (até o primeiro ponto, sem os pontos de arquivo oculto) é testado e mascarado, e destinos de link são mascarados sem `#`/`?` com o sufixo devolvido.
- **Cópia vendorizada:** `.org-atlas/skill/scripts/atlas.py` diferente da skill instalada vira AVISO `config` ("cópia da skill desatualizada — rode `vendor`") e continua varrida; só as ocorrências cujo texto também está no `atlas.py` instalado (as regex da ferramenta) são descartadas.
- **`context`:** o nome do serviço vai entre crases no título e crases/quebras de linha dos valores são neutralizadas no Markdown.
- `ATLAS_VERSION` e `version` do plugin 2026.11.6; `curation.md`, `maintenance.md`, `modes.md`, `context.md` e CHANGELOG da `boson-atlas`.

### Como foi feito
- Testes em da4c65f (UT-01 a UT-07 e IT-01, em `test_curate.py`, `test_context.py`, `test_lint.py` e `test_vendor.py`) e 2dbff53 (regressão da revisão); correções em 09b6c30 e ce53b6c.
- **Revisão G4:** rodada 1 REPROVADO (major: a primeira versão pulava a cópia desatualizada inteira, e um segredo plantado nela passava com exit 0); rodada 2 APPROVED.

### Prova de Correção
- **Antes:** da4c65f vermelho (19 falhas por asserção; por exemplo o arquivo da convenção crescendo de 987 para 1032 bytes, 2 arquivos em vez de 3 na colisão, `PR #３` aceito, `### ## Convenções (regra)` no pacote, `abcd1234` na saída do `lint`, `secret-leak` falso na cópia e `pr-title-conventional-acme-a.md` criado depois da rejeição); 2dbff53 vermelho ("segredo plantado em .org-atlas/skill/scripts/atlas.py não virou secret-leak").
- **Depois (ce53b6c):** suíte completa verde (boson-atlas 375 testes, 1 skip antigo), também no Python 3.14 local e no 3.15 da CI.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Marcador `atlas:end evidence` no nome ou padrão não faz o arquivo crescer em quatro `propose` | PASS | `test_curate.py::EvidenceRegionTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | `acme/a-b` × `acme-a/b` dão ids e arquivos diferentes, estáveis na ordem dos sinais | PASS | `test_curate.py::IdCollisionTest`, `IdCollisionCliTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | `--via` com dígito não ASCII sai com 2 | PASS | `test_curate.py::AsciiViaTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Serviço chamado `## Convenções (regra)` não imita título de seção | PASS | `test_context.py::ServiceNameHeadingTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-05 | Caminho inteiro, radical e link mascarados no `lint`, em texto e `--json` | PASS | `test_lint.py::WholePathMaskTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-06 | Cópia vendorizada desatualizada: AVISO `config`, sem `secret-leak` falso, e segredo plantado nela ou em outro arquivo continua ERRO | PASS | `test_vendor.py::OutdatedCopyTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| UT-07 | Rejeição por `(kind, pattern)` vale em qualquer escopo, não para outro padrão | PASS | `test_curate.py::RejectionRuleTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Rejeitada a da organização, nenhuma `pr-title-conventional-<repo>`; outro padrão do mesmo kind continua proposto | PASS | `test_curate.py::RejectionScopeCliTest` — CI do PR #31 (run 43699264213, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — da4c65f/2dbff53 vermelhos, 09b6c30/ce53b6c verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 2
- [x] Padrão existente mantido — sufixo por hash como o `slug` da SPEC-0036; máscara e achados do `lint` da SPEC-0039
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `curation.md`, `maintenance.md`, `modes.md`, `context.md`, CHANGELOG `[2026.11.6]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma

### Deploy
N/A — `ATLAS_VERSION` 2026.11.6, PR #31.

### Pendências
Nenhuma nova spec. Limites documentados e nits da revisão: o id de um repositório muda quando outro passa a colidir com ele; padrões com o mesmo `_id_part` (`feat/` × `feat-`) colidem e contam como o mesmo padrão na rejeição; recolisão com um nome de repositório montado para isso; dois `extra_patterns` sobrepostos podem mostrar parte do valor; padrão ancorado não mascara `#fragmento`/`?query`; arquivo oculto sem teste próprio; a cópia vendorizada não é varrida quando o próprio `lint` roda dela (como na `main`). Ferramenta: o título gerado por `spec_graph.py pr` passou de novo do `pr_title_max` (101).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
