---
id: SPEC-0039
title: "org-atlas: lint do atlas"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: [SPEC-0037@2]
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/maintenance.md, skills/org-atlas/tests/test_lint.py, skills/org-atlas/tests/fixtures/lint/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011, ADR-0012]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0039 — org-atlas: lint do atlas

## 1. Visão Geral
Implementa o `atlas.py lint`, que só lê e aponta o que precisa de atenção no atlas:
- segredo em qualquer arquivo, inclusive em texto escrito por pessoas;
- fato velho e coletor que falhou;
- referência quebrada;
- convenção esperando decisão;
- configuração inválida;
- página de entidade que sumiu há muito tempo.

É a última barreira contra vazamento e o que mantém o atlas confiável.

## 2. Motivação & Escopo
**Motivação:** a redaction do `scan` só cobre o que entra pelos coletores; uma pessoa pode colar um segredo numa nota. E um atlas que ninguém mantém leva o agente a errar (SPEC-0029).

**Objetivos (dentro do escopo):**
- Regras de erro: `secret-leak`, `config`, `failed-collector`.
- Regras de aviso: `stale`, `broken-ref`, `pending-convention`, `orphan-page`.
- `lint [--json] [--only regra,...]`, no formato do `lint` da `second-brain` (SPEC-0023).
- `references/maintenance.md` com cada regra e a sugestão de correção.

**Não-objetivos (fora do escopo):**
- Corrigir sozinho: o `lint` só aponta (a única ação é do humano ou do agente com o humano).
- Detecção de segredo por entropia (mesmos padrões da SPEC-0033).

## 3. Dependências
- **Implementações necessárias:** SPEC-0036 — `graph.json`, páginas e `_scan.json`.
- **Contratos consumidos:** SPEC-0037@1 — formato das convenções (para `pending-convention`).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** a referência é o `lint` da `second-brain` (`skills/second-brain/scripts/brain.py`, SPEC-0023): uma linha `<ERRO|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)` por achado, resumo final, `--only` e exit 0/1/2.

**Decisão:** mesmo formato; `secret-leak` reaproveita a função `redact` da SPEC-0033 em modo de detecção, sobre todos os arquivos do atlas.

**Justificativa:** um único conjunto de padrões de segredo para entrada e verificação; formato já conhecido.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** mascarar segredo encontrado em nota do time (reescreveria texto humano, contra o ADR-0010).

**ADRs:** ADR-0010, ADR-0011, ADR-0012.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** atlas com 500 serviços em menos de 3 s.
- **Segurança:** a linha de `secret-leak` mostra o arquivo, a linha e o tipo do padrão, **nunca** o valor (IT-02).
- **Privacidade e dados pessoais:** N/A além da regra acima.
- **Disponibilidade e resiliência:** arquivo ilegível → achado `config` e o lint segue.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `lint`.

```text
atlas.py lint [--json] [--only regra,...]
  uma linha por achado: "<ERRO|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)"; resumo "N erros, M avisos"
  ERRO  secret-leak         arquivo:linha com padrão de segredo — "padrão <tipo>", nunca o valor
  ERRO  config              atlas-config.yml inválido, caminho absoluto, chave desconhecida, arquivo ilegível
  ERRO  failed-collector    coletor com status failed no _scan.json
  AVISO stale               coletor com seen_at além de stale_days
  AVISO broken-ref          aresta apontando para nó inexistente; link entre páginas para arquivo inexistente
  AVISO pending-convention  convenção inferred esperando confirm ou reject
  AVISO orphan-page         página de entidade não vista há mais de 2 × stale_days
  exit 0 sem ERRO, 1 com ERRO, 2 com regra desconhecida em --only; 3 sem configuração
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Atlas limpo | nada fora das regras | "0 erros, 0 avisos", exit 0 | IT-01 |
| Segredo em nota | token colado em `services/x.md` | ERRO `secret-leak` com arquivo e linha, sem o valor; exit 1 | UT-01, IT-02 |
| Configuração | caminho absoluto ou chave desconhecida | ERRO `config` | UT-02 |
| Coletor | falhou / velho | ERRO `failed-collector` / AVISO `stale` | UT-03 |
| Referência | aresta ou link para o que não existe | AVISO `broken-ref` | UT-04 |
| Convenção | `inferred` esperando | AVISO `pending-convention` | UT-05, CT-01 |
| Página órfã | entidade não vista há mais de 2 × `stale_days` | AVISO `orphan-page` | UT-06 |
| Filtro | `--only stale` / regra desconhecida | só a regra / exit 2 | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado arquivos com cada padrão de segredo da SPEC-0033, quando `secret-leak` roda, então cada um é achado com arquivo, linha e tipo, sem o valor.
- **UT-02** — Dado um `atlas-config.yml` com caminho absoluto e outro com chave desconhecida, quando `config` roda, então os dois são ERRO.
- **UT-03** — Dado um `_scan.json` com um coletor `failed` e outro de 20 dias com `stale_days: 14`, quando as regras rodam, então há um ERRO e um AVISO.
- **UT-04** — Dado uma aresta para nó inexistente e um link para página inexistente, quando `broken-ref` roda, então há dois AVISOs.
- **UT-05** — Dado convenções `inferred`, `confirmed` e `rejected`, quando `pending-convention` roda, então só a `inferred` gera AVISO.
- **UT-06** — Dado uma página "Não visto desde" há 30 dias com `stale_days: 14`, quando `orphan-page` roda, então há AVISO; com 20 dias, não.

### 7.3 Testes de Integração
- **IT-01** — `lint` pela CLI num atlas de fixture limpo sai com 0 e "0 erros, 0 avisos".
- **IT-02** — Com um token colado numa nota de `services/<id>.md`, o `lint` sai com 1, aponta arquivo e linha, e o valor do token não aparece na saída.
- **IT-03** — `lint --only stale` mostra só essa regra; `--only nao-existe` sai com 2.

### 7.4 Testes de Contrato
- **CT-01** — O `lint` lê os arquivos de convenção no formato da SPEC-0037@1 (fixtures geradas pelo `curate`).

### 7.5 Testes E2E
- N/A — comando usado pelo agente e pela CI do atlas; sem jornada de interface.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** atlas de fixture com os casos de cada regra.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto; no modo repositório, o workflow da SPEC-0040 roda o `lint` no PR do atlas.
- **Dados/schema:** N/A — só leitura.
- **Compatibilidade:** N/A.
- **Observabilidade:** a própria saída do `lint`.
- **Rollback:** reverter o PR.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Regras**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, CT-01 com a tag `SPEC-0039:<ID>`, falhando pelo motivo certo
- [x] Green: as sete regras, com `secret-leak` reaproveitando `redact`
- [x] Refactor mantendo tudo verde

**Fase 2: Comando lint**
- [x] Red: IT-01, IT-02, IT-03 com a tag `SPEC-0039:<ID>`, falhando pelo motivo certo
- [x] Green: `lint` com `--only` e `--json`; `references/maintenance.md` e `SKILL.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Seção em `[Unreleased]` do `skills/org-atlas/CHANGELOG.md`; o `ATLAS_VERSION` sobe no fim do épico, no mesmo PR #20

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: skill distribuída por cópia (como a second-brain)
- [x] Relatório de Entrega, README e `skills/org-atlas/CHANGELOG.md` (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=9, errors=16)); nota: red da org-atlas conferido em worktree limpa em dc295e8: FAILED (failures=9, errors=16), só testes da SPEC-0039; se a cadeia parar antes, é o SPEC-0004:IT-10 (tempo, sob carga) — dc295e8 | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 6bb888d | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 6bb888d | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 3, 6bb888d): APPROVED — B1 da rodada 2 corrigido (máscara por componente e por radical em path, detail, suggestion, --json e stderr); rodadas anteriores conferidas de novo; 3 menores de máscara em padrões extras montados para isso, na SPEC-0048 — 6bb888d | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do PR #20 em 6058173 verde (run 41494254877 Python 3.9/3.15; run 41494258273 sdd/pr-check) — 6058173 | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 66d94de | 2026-11-02 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
`atlas.py lint [--only REGRAS] [--json]`: diagnóstico só de leitura do atlas antes de compartilhar ou commitar. Regras `secret-leak` (padrões de segredo da redaction, em conteúdo e em nomes), `config`, `failed-collector`, `stale`, `broken-ref`, `pending-convention` e `orphan-page`, com ERRO ou AVISO, caminho, detalhe e sugestão. Sai com 1 só quando há erro. Nunca mostra o valor de um segredo, nem em parte, nem no `--json`.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `lint_rules`, `run_lint` e `cmd_lint` no `atlas.py`: uma passada pelo atlas com `os.walk`, só arquivos regulares (`lstat`, `O_NOFOLLOW|O_NONBLOCK`, `fstat`, limite de 32 MB), ignorando `.git` e outras pastas de VCS; reusa `SECRET_PATTERNS` e `extra_patterns` da redaction; lê só a configuração local para achar o atlas.
- **Revisão G4 (3 rodadas):** a 1ª achou o token inteiro saindo no campo "sugestão" e na mensagem de YAML inválido, configuração quebrada derrubando o lint, symlinks seguidos para fora do atlas e `/dev/zero`/FIFO travando, e pasta ilegível dando "0 erros". A 2ª achou um padrão extra ancorado (`^…$`) acusando e imprimindo o valor, porque nomes eram verificados por componente e mascarados no caminho inteiro. A 3ª aprovou: todo campo mascarado, caminhos por componente e por radical, arquivo ilegível vira achado e o lint segue. Testes de regressão antes de cada correção (bb0fbcd/18db97f, af97e48/6bb888d).
- **Incidente:** a primeira execução do teste com symlink para `/dev/zero` esgotou a memória da máquina e reiniciou a sessão — exatamente o defeito corrigido. O teste roda com timeout e limite de memória no Linux e é pulado no macOS, que não aplica esse limite.
- Guia `references/maintenance.md`; `SKILL.md` com o fluxo "Manutenção (lint)"; CHANGELOG em `[Unreleased]`.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`.

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Cada padrão de segredo vira ERRO secret-leak com arquivo:linha e tipo, sem o valor; segredo em nome de arquivo ou pasta, em arquivo não UTF-8 e por padrão extra ancorado; nenhum campo nem a saída de erro mostra o valor | PASS | `test_lint.py::SecretLeakTest` e testes das rodadas 2 e 3 — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | atlas-config.yml com caminho absoluto, chave desconhecida, YAML inválido, não UTF-8, ilegível ou ausente vira ERRO config e o lint segue; arquivos especiais, symlinks e pastas ilegíveis viram achado sem serem lidos; formatos inválidos sem traceback | PASS | `ConfigTest` e testes das rodadas 2 e 3 — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | Coletor failed vira ERRO; passado de stale_days vira AVISO stale | PASS | `CollectorTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Aresta para nó inexistente e link quebrado viram AVISO broken-ref; links em blocos de código ignorados; %xx decodificado; fora do atlas é broken-ref; links para pasta ilegível não são acusados | PASS | `BrokenRefTest` e testes das rodadas 2 e 3 — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| UT-05 | Só convenções inferred viram AVISO pending-convention | PASS | `PendingConventionTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| UT-06 | Página "Não visto desde" há mais de 2 × stale_days vira AVISO orphan-page | PASS | `OrphanPageTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Atlas limpo: exit 0, 0 erros, 0 avisos, nada escrito; sem configuração sai com 3; guia cobre todas as regras | PASS | `CleanFixtureTest`, `CleanAtlasTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| IT-02 | Token colado numa página: exit 1 com a linha do achado, sem o valor no texto nem no --json | PASS | `SecretInNoteTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| IT-03 | `--only` filtra e respeita a ordem; regra desconhecida sai com 2 | PASS | `OnlyTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |
| CT-01 | Lê as convenções geradas pela curadoria (SPEC-0037@2): inferidas avisam, decididas não | PASS | `ConventionFilesContractTest` — CI do PR #20 em 6058173 (run 41494254877, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #20 em 6058173
- [x] Review independente sem achados blocker/major (G4) — 3ª rodada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — 500 serviços em 0,11–0,30 s pela CLI (meta 3 s); só leitura conferida por hash dos arquivos; arquivo ilegível vira achado e o lint segue (UT-02)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — relatório do próprio `lint` e `--json`; rollback por revert
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README, `SKILL.md`, `references/maintenance.md` e `skills/org-atlas/CHANGELOG.md`
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0048

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
N/A — skill distribuída por cópia; em `[Unreleased]` na branch `sdd/SPEC-0029`, PR #20.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- SPEC-0048 — máscara de padrões extras que atravessam `/`, radical de nomes com vários pontos e de arquivos ocultos, destinos de link com `#`/`?` (menores da 3ª rodada do G4).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0039`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
