---
id: SPEC-0034
title: "org-atlas: coletores generic e GitHub"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0032]
consumes_contract: [SPEC-0033@1]
contract_version: 1
touches: [skills/org-atlas/assets/collectors/generic.py, skills/org-atlas/assets/collectors/github.py, skills/org-atlas/references/collectors/generic.md, skills/org-atlas/references/collectors/github.md, skills/org-atlas/tests/test_collector_generic.py, skills/org-atlas/tests/test_collector_github.py, skills/org-atlas/tests/fixtures/generic/**, skills/org-atlas/tests/fixtures/github/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0034 — org-atlas: coletores generic e GitHub

## 1. Visão Geral
Entrega os dois primeiros coletores, como scripts separados em `assets/collectors/`, que a organização declara no `atlas-config.yml`:
- **`generic`:** transforma um arquivo de fatos escrito à mão (JSON) na saída do contrato. Serve para o que nenhum coletor cobre e é o exemplo de como escrever um coletor próprio.
- **`github`:** categoria `code`. Lê, pelo `gh` da máquina, os repositórios de uma organização, os workflows de CI, os donos (CODEOWNERS) e uma amostra de PRs, que vira sinal para a curadoria (padrão de título, de branch e forma de merge).

## 2. Motivação & Escopo
**Motivação:** o MVP precisa de código e entrega para montar o grafo quase sem credencial sensível (SPEC-0029). GitHub é o provedor de código escolhido; o `generic` garante que qualquer organização comece mesmo sem coletor pronto.

**Objetivos (dentro do escopo):**
- `generic.py --facts ARQUIVO --category C [--source NOME]`.
- `github.py --org ORG [--repos a,b] [--pr-sample N] [--input PASTA]`: repositórios, linguagem, branch padrão, tópicos, arquivado; workflows (`pipeline` + `builds`); CODEOWNERS (`team` + `owns`); sinais de PR (contagem de títulos em Conventional Commits, com chave de ticket `ABC-123`, prefixos de branch, forma de merge, presença de template de PR) e amostra de até 10 títulos.
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
             {type: "merge-methods", repository, total, counts: {merge, squash, rebase}}
             {type: "pr-template", repository, present: true|false}
  --input PASTA: lê repos.json, workflows/<repo>.json, codeowners/<repo>, pulls/<repo>.json em vez do gh
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

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0034`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
