---
id: SPEC-0048
title: "org-atlas: endurecimento da curadoria, do context e do lint, e alcance da rejeição"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-02
parent:
depends_on: [SPEC-0037, SPEC-0038, SPEC-0039, SPEC-0040]
consumes_contract: []
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/test_curate.py, skills/boson-atlas/tests/test_context.py, skills/boson-atlas/tests/test_lint.py, skills/boson-atlas/tests/test_vendor.py, skills/boson-atlas/references/modes.md, skills/boson-atlas/references/maintenance.md, skills/boson-atlas/references/context.md, skills/boson-atlas/references/curation.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0012]
external: []
size: S
approved_by:
approved_at:
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
- **IT-01** — Dado `pr-title-conventional` rejeitada no escopo organization, quando a maioria muda e só um repositório segue o padrão, então nenhuma proposta `pr-title-conventional-<repo>` é criada e o `curate list` mostra só a rejeitada; um padrão diferente do mesmo kind continua sendo proposto.

## 5. Questões em Aberto
- [x] Uma rejeição vale para o kind+padrão em qualquer escopo (não propõe `pr-title-conventional-<repo>` depois de rejeitar a da organização) ou só para o mesmo id, como hoje? — Para o kind+padrão em qualquer escopo: quem rejeita a regra rejeita a regra, não o escopo; é a leitura de "rejeitada nunca volta" do ADR-0012 (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)

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
