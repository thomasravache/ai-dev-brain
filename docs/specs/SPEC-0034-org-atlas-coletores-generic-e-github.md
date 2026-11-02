---
id: SPEC-0034
title: "org-atlas: coletores generic e GitHub"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0032]
consumes_contract: [SPEC-0033@1]
contract_version: 2
touches: [skills/org-atlas/assets/collectors/generic.py, skills/org-atlas/assets/collectors/github.py, skills/org-atlas/references/collectors/generic.md, skills/org-atlas/references/collectors/github.md, skills/org-atlas/tests/test_collector_generic.py, skills/org-atlas/tests/test_collector_github.py, skills/org-atlas/tests/fixtures/generic/**, skills/org-atlas/tests/fixtures/github/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0034 — org-atlas: coletores generic e GitHub

## 1. Visão Geral
Entrega os dois primeiros coletores, como scripts separados em `assets/collectors/`, que a organização declara no `atlas-config.yml`:
- **`generic`:** transforma um arquivo de fatos escrito à mão (JSON) na saída do contrato. Serve para o que nenhum coletor cobre e é o exemplo de como escrever um coletor próprio.
- **`github`:** categoria `code`. Lê, pelo `gh` da máquina, os repositórios de uma organização, os workflows de CI, os donos (CODEOWNERS) e uma amostra de PRs, que vira sinal para a curadoria (padrão de título e de branch, formas de merge permitidas e template de PR).

## 2. Motivação & Escopo
**Motivação:** o MVP precisa de código e entrega para montar o grafo quase sem credencial sensível (SPEC-0029). GitHub é o provedor de código escolhido; o `generic` garante que qualquer organização comece mesmo sem coletor pronto.

**Objetivos (dentro do escopo):**
- `generic.py --facts ARQUIVO --category C [--source NOME]`.
- `github.py --org ORG [--repos a,b] [--pr-sample N] [--input PASTA]`: repositórios, linguagem, branch padrão, tópicos, arquivado; workflows (`pipeline` + `builds`); CODEOWNERS (`team` + `owns`); sinais de PR (contagem de títulos em Conventional Commits, com chave de ticket `ABC-123`, prefixos de branch) e amostra de até 10 títulos; formas de merge permitidas no repositório e presença de template de PR (Emenda v2).
- `--input PASTA` lê respostas gravadas em vez de chamar o `gh`, para testes e para quem roda sem acesso.
- Guias `references/collectors/generic.md` e `github.md`: como declarar, permissões mínimas do token (só leitura), limites.

**Não-objetivos (fora do escopo):**
- GitLab e outros provedores: entram depois como guias e coletores novos (SPEC-0029).
- Ler corpo de PR, conteúdo de código ou issues.
- Chamar a API do GitHub direto por HTTP: o coletor usa o `gh` já autenticado na máquina.

## 3. Dependências
- **Implementações necessárias:** SPEC-0032 — estrutura de testes e checadores de arquitetura.
- **Contratos consumidos:** SPEC-0033@1 — formato da saída do coletor (ADR-0011).
- **Pré-requisitos externos:** `gh` instalado e autenticado com permissão de leitura na organização (só para uso real; os testes usam `--input` e um `gh` falso).

## 4. Decisão Arquitetural
**Contexto:** coletores são processos externos declarados (ADR-0010), como os processadores da `second-brain` (ADR-0009, `references/processors.md`). Cada coletor é um script único só com a biblioteca padrão, como o `atlas.py`.

**Decisão:** `github.py` chama `gh api` com `--paginate` por `subprocess` (é o coletor, não o `atlas.py`, que fala com o provedor) e monta a saída do contrato. A contagem de padrões fica no coletor; só números e uma amostra pequena saem dele.

**Justificativa:** o `gh` resolve autenticação e paginação sem guardar token em lugar nenhum da skill; `--input` deixa o coletor testável sem rede.

**Desvio do padrão existente:** Nenhum. O teste de arquitetura da SPEC-0032 passa a cobrir `assets/collectors/`: só biblioteca padrão e `subprocess` só para o executável do provedor.

**Alternativas descartadas:** HTTP direto com `urllib` (exigiria a skill lidar com o token); guardar todos os títulos de PR (dado demais e sem necessidade para a curadoria).

**ADRs:** ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** organização com 300 repositórios e `--pr-sample 200` em menos de 5 min de chamadas ao `gh` (medido num uso real, sem bloquear o MVP).
- **Segurança:** o coletor nunca lê nem imprime o token; o guia recomenda token só de leitura; nenhum conteúdo de código é lido.
- **Privacidade e dados pessoais:** títulos de PR podem citar pessoas ou clientes: só uma amostra de até 10 sai, e passa pela redaction do `scan`; logins de autores não são coletados.
- **Disponibilidade e resiliência:** `gh` ausente, não autenticado ou organização inexistente → exit 1 com mensagem clara, sem traceback.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** chamadas à API do GitHub dentro do limite do token.

## 6. Artefato A — Contrato
**Interface:** `generic.py` e `github.py` (argumentos, saída no contrato do ADR-0011, códigos de saída) e o formato do arquivo de fatos.

```text
generic.py --facts ARQUIVO --category C [--source NOME]
  ARQUIVO (JSON): {"entities": [{"kind","id","name","attrs"}], "relations": [{"from","to","type"}]}
  saída: contrato org-atlas/collector@1 com collector "generic", category C, source NOME (padrão "generic")
  arquivo inexistente ou JSON inválido: exit 1 "<arquivo>: <motivo>"; entidade sem kind/id: exit 1 com o índice

github.py --org ORG [--repos a,b] [--pr-sample N (padrão 100)] [--input PASTA]
  entidades: repository:<org>/<nome> {language, default_branch, topics, archived, visibility}
             pipeline:<org>/<nome>/<workflow> {file}
             team:<org>/<time>
  relações:  pipeline → repository (builds); team → repository (owns, via CODEOWNERS)
  sinais:    {type: "pr-titles", repository, total, pattern_counts: {conventional, ticket_key, other}, sample: [≤10]}
             {type: "branch-prefixes", repository, total, counts: {"feat/": n, ...}}
             {type: "merge-methods", repository, present: {merge: bool, squash: bool, rebase: bool}}   (v2)
               fonte: allow_merge_commit / allow_squash_merge / allow_rebase_merge de GET repos/{org}/{repo};
               sem esses campos na resposta (token sem permissão): sinal omitido e aviso no stderr
             {type: "pr-template", repository, present: {pr_template: bool}}   (v2)
               fonte: contents API em .github/, raiz e docs/ — pull_request_template.md (qualquer caixa)
               ou a pasta PULL_REQUEST_TEMPLATE/
  --input PASTA: lê repos.json, workflows/<repo>.json, codeowners/<repo>, pulls/<repo>.json,
               repo/<repo>.json (resposta de GET repos/{org}/{repo}) e pr-template/<repo> (arquivo existir = template
               presente) em vez do gh   (v2)
  gh não encontrado: exit 1 "gh não encontrado — instale e autentique (references/collectors/github.md)"
  gh sem autenticação ou sem acesso: exit 1 "gh sem acesso à organização ORG"
  organização inexistente: exit 1 "organização não encontrada: ORG"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Fatos à mão | arquivo de fatos válido | saída no contrato | UT-05, IT-04, CT-01 |
| Fatos inválidos | JSON inválido ou entidade sem `id` | exit 1 com o motivo | IT-04 |
| Repositórios | resposta de repos | entidades `repository` com os atributos | UT-02, IT-01 |
| Workflows | arquivos de workflow | `pipeline` + `builds` | UT-03, IT-01 |
| Donos | CODEOWNERS | `team` + `owns` | UT-04, IT-01 |
| Sinais de PR | amostra de PRs | contagens e amostra ≤ 10 | UT-01, IT-01 |
| Política e template (v2) | `allow_*` do repositório e arquivos de template | `merge-methods` e `pr-template` com `present` de booleanos; sem `allow_*`, sinal omitido com aviso | UT-06, IT-01 |
| Pelo `gh` | `gh` falso no PATH | mesma saída que com `--input` | IT-02, CT-01 |
| Sem acesso | `gh` falso falhando autenticação | exit 1 com a mensagem | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — coletores novos.

### 7.2 Testes Unitários
- **UT-01** — Dado títulos de PR variados, quando os padrões são contados, então Conventional Commits, chave de ticket e "outros" batem, e a amostra tem no máximo 10.
- **UT-02** — Dado a resposta de um repositório, quando é mapeada, então vira `repository:<org>/<nome>` com os atributos do contrato e nenhum outro.
- **UT-03** — Dado a lista de workflows de um repositório, quando é mapeada, então gera um `pipeline` por workflow e a relação `builds`.
- **UT-04** — Dado um CODEOWNERS com times e usuários, quando é lido, então só times viram `team` com `owns`; usuários são ignorados.
- **UT-06** — Dado a resposta de um repositório com `allow_merge_commit`, `allow_squash_merge` e `allow_rebase_merge`, e a presença ou não de template, quando os sinais são montados, então `merge-methods` e `pr-template` têm `present` só com booleanos; sem os campos `allow_*`, o sinal `merge-methods` é omitido e há um aviso (v2).
- **UT-05** — Dado um arquivo de fatos, quando o `generic` converte, então a saída tem o cabeçalho do contrato e as entidades com `source`.

### 7.3 Testes de Integração
- **IT-01** — `github.py --input` com as fixtures de uma organização de exemplo gera a saída esperada (repositórios, pipelines, times e sinais).
- **IT-02** — Com um `gh` falso no `PATH` que responde com as mesmas fixtures, `github.py` sem `--input` gera a mesma saída.
- **IT-03** — Com um `gh` falso que falha a autenticação, `github.py` sai com 1 e a mensagem do contrato.
- **IT-04** — `generic.py` com um arquivo válido gera a saída; com JSON inválido ou entidade sem `id`, sai com 1 e o motivo.

### 7.4 Testes de Contrato
- **CT-01** — A saída de `generic.py` e de `github.py` (fixtures) passa no `validate_collector_output` da SPEC-0033@1, e o `scan` de um atlas com os dois coletores declarados termina com OK.

### 7.5 Testes E2E
- N/A — coletores chamados pelo `scan`; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- Teste de arquitetura estendido a `assets/collectors/` (SPEC-0032:UT-05).

**Dublês e dados de teste:** fixtures gravadas de uma organização fictícia (`acme`) e um `gh` falso em Python no `PATH`.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto; o coletor só roda quando declarado no `atlas-config.yml`.
- **Dados/schema:** N/A.
- **Compatibilidade:** contrato `org-atlas/collector@1`.
- **Observabilidade:** relatório do `scan`.
- **Rollback:** remover o coletor do `atlas-config.yml` ou reverter o PR.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Provedor de código do MVP — GitHub; GitLab entra depois (thomas, 2026-10-30)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Coletor generic**
- [x] Red: UT-05, IT-04 com a tag `SPEC-0034:<ID>`, falhando pelo motivo certo
- [x] Green: `assets/collectors/generic.py` e `references/collectors/generic.md`
- [x] Refactor mantendo tudo verde

**Fase 2: Coletor GitHub**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-06, IT-01, IT-02, IT-03 com a tag `SPEC-0034:<ID>`, falhando pelo motivo certo
- [x] Green: `assets/collectors/github.py` com `--input`, fixtures da organização `acme`, `gh` falso e `references/collectors/github.md`
- [x] Refactor mantendo tudo verde

**Fase 3: Contrato**
- [x] Red: CT-01 com a tag `SPEC-0034:<ID>`, falhando pelo motivo certo
- [x] Green: ajustes para a saída passar no validador da SPEC-0033@1; teste de arquitetura cobrindo `assets/collectors/` (biblioteca padrão pela SPEC-0032:UT-05; regra de `subprocess` na SPEC-0046)
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Seção em `[Unreleased]` do `skills/org-atlas/CHANGELOG.md`; o `ATLAS_VERSION` sobe na SPEC-0036, no mesmo PR #20 (`atlas.py` fora do `touches`)

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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=18, errors=12)) — bbc684f | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 0ef159b | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 0ef159b | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 2, 0ef159b): APPROVED — M1 e menores 1–4 corrigidos; 3 notas cosméticas — 0ef159b | 2026-11-02 |
| G5 Integração & CI | PASS | MANUAL: suíte completa verde no CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15; run 41415077615 sdd/pr-check) e local antes do push; os 2 FAIL locais são só SPEC-0004:IT-10 (limite de 2 s), que falha também na main sem mudança na sdd-management — máquina com load average 13 | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 4988602 | 2026-11-02 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-31 | G1 | spec | SPEC_DEFECT do Test-writer: o sinal merge-methods não tem fonte (a API de PRs não informa o método de merge) e o pr-template não tem entrada no --input nem fonte definida; o present de pr-template precisa ser objeto de booleanos (regra de tipos da SPEC-0033) | leitura da spec, ADR-0010/0011, collector-contract.md e do validador; nenhum teste escrito | thomas | Emenda v2 (aprovada por thomas em 2026-11-02): merge-methods vira política do repositório e pr-template ganha fonte e entrada | 2026-11-02 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
Dois coletores da `org-atlas` chamados pelo `scan`: o `generic` converte um arquivo de fatos escrito à mão na saída `org-atlas/collector@1`; o `github` mapeia uma organização do GitHub (repositórios, pipelines dos workflows, times do CODEOWNERS) e gera os sinais de convenção `pr-titles`, `branch-prefixes`, `merge-methods` e `pr-template`, só com contagens e uma amostra de até 10 títulos — sem logins de autores, corpo de PR ou código. `--input` permite rodar com respostas gravadas, sem rede.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `assets/collectors/generic.py` e `github.py`: scripts de biblioteca padrão no padrão do `atlas.py` (funções puras de mapeamento, classe de erro, `main` que devolve o exit code, `erro:` no stderr). O `github.py` chama `gh api` por `subprocess` com lista de argumentos, sem shell, timeout de 120 s e prompts desligados; listas com `--paginate` lidas como fluxo de JSON; PRs paginados à mão até `--pr-sample`.
- **Emenda v2** (IMP-01): `merge-methods` vira a política do repositório (`allow_*`) e `pr-template` ganha fonte (contents API em `.github/`, raiz e `docs/`) e entrada no `--input`; UT-06 novo.
- **Revisão G4** (2 rodadas): a 1ª achou vazamento de logins em `branch-prefixes` (branches `<login>/...`), contra a seção 5. Correção sem mudar o contrato: só prefixos de tipo conhecidos viram chave; o resto conta só no total. Na mesma rodada: times, `--org` e `--repos` sem diferença de caixa, ids pelo `full_name`, mensagem própria para o limite de requisições e robustez a entradas estranhas, cada um com teste de regressão (3545a4d) antes da correção (0ef159b).
- Guias em `references/collectors/generic.md` e `github.md`; entrada em `[Unreleased]` do `skills/org-atlas/CHANGELOG.md`.
- **Dívidas conhecidas (cosméticas, da revisão):** ids de repositório mantêm a caixa da API enquanto os de time são minúsculos; o aviso de repositório não encontrado mostra o nome em minúsculas.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`.

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Padrões de título e prefixos de branch | PASS | `test_collector_github.py::TitlePatternsTest` (3 testes + `test_branch_prefixes_count_only_known_types`) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| UT-02 | Repositório só com os atributos do contrato, id pelo `full_name` | PASS | `MapRepositoryTest` (2 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| UT-03 | Um `pipeline` por workflow e `builds`; saída paginada | PASS | `MapWorkflowsTest` (3 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| UT-04 | Só times do CODEOWNERS viram `team` + `owns`, sem diferença de caixa | PASS | `ParseCodeownersTest` (3 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| UT-05 | Fatos viram a saída do contrato com `source` | PASS | `test_collector_generic.py::ConvertFactsTest` (2 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| UT-06 | `merge-methods` e `pr-template` com `present` de booleanos; omissão com aviso | PASS | `MapPolicyTest` (3 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| IT-01 | `--input` gera a saída esperada; `--pr-sample`, `--repos`, caixa, logins, CODEOWNERS não UTF-8 | PASS | `InputFolderTest` (7 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| IT-02 | `gh` falso no PATH dá a mesma saída; paginação real e mais de uma página | PASS | `FakeGhTest` (5 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| IT-03 | `gh` sem autenticação, ausente, organização inexistente, 403 e limite de requisições saem com 1 | PASS | `GhFailureTest` (5 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| IT-04 | `generic.py` válido sai com 0; arquivo inválido ou fato sem `kind`/`id` sai com 1 e o motivo | PASS | `GenericCliTest` (3 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |
| CT-01 | Saídas passam no `validate_collector_output` e o `scan` com os dois coletores termina OK | PASS | `GenericContractTest` + `GithubContractTest` (3 testes) — CI do PR #20 em b5c8120 (run 41415077562, Python 3.9 e 3.15) e suíte local em 0ef159b (G2) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #20 em b5c8120
- [x] Review independente sem achados blocker/major (G4) — 2ª rodada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — segurança, privacidade e resiliência provadas por IT-01/IT-03 e pela revisão; desempenho com 300 repositórios fica para o primeiro uso real, como a seção 5 prevê (sem bloquear o MVP)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — relatório do `scan`; rollback removendo o coletor do `atlas-config.yml`
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README, `skills/org-atlas/CHANGELOG.md` e guias dos coletores
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0046 e SPEC-0036

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
N/A — skill distribuída por cópia; na branch `sdd/SPEC-0029`, PR #20, em `[Unreleased]` do CHANGELOG da skill.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- SPEC-0046 — regra de arquitetura dos coletores (`subprocess` só para o executável do provedor, sem shell; UT-04 dela), que pedia `test_architecture.py`, fora do `touches` desta spec.
- SPEC-0036 — sobe o `ATLAS_VERSION` e liga os guias novos no `SKILL.md` no mesmo PR #20 (ADR-0010: versão e CHANGELOG no mesmo PR); `atlas.py` e `SKILL.md` estão fora do `touches` desta spec.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0034`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-31 | Sinal `merge-methods` passa a ser a política do repositório (`present` com `merge`/`squash`/`rebase` de `allow_*`), não a contagem por PR; `pr-template` com `present: {pr_template: bool}` e fonte definida; `--input` ganha `repo/<repo>.json` e `pr-template/<repo>`; UT-06 novo | SPEC_DEFECT no G1 (IMP-01): a API de PRs não informa o método de merge, o template não tinha fonte, e as regras de tipo da SPEC-0033 exigem `present` como objeto de booleanos | nenhuma (sem consumidores do contrato) | thomas, 2026-11-02 |
