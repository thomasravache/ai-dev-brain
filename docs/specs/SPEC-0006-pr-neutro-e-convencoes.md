---
id: SPEC-0006
title: PR neutro, convenções do time e documentação do modo privado
tier: full
type: feature
user_facing: false
status: approved
created: 2026-10-14
parent: SPEC-0002
depends_on: [SPEC-0004, SPEC-0005]
consumes_contract: [SPEC-0003@1]
contract_version: 1
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/references/private-mode.md, skills/sdd-management/SKILL.md, README.md, CHANGELOG.md]
adrs: [ADR-0006]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0006 — PR neutro, convenções do time e documentação do modo privado

## 1. Visão Geral
Fecha o modo privado: o `private init` detecta as convenções do time (forma de merge, padrão de mensagens, gerenciador de hooks, template de PR) e grava no sdd-config do `spec_root`; o `pr` em modo privado gera título e corpo no padrão do time, sem nenhuma marca do SDD e passando pelo `leak-check`; e o agente ganha as instruções do modo (`references/private-mode.md` e um parágrafo no `SKILL.md`). O teste da jornada completa prova o objetivo do épico.

## 2. Motivação & Escopo
**Motivação:** o PR é o que o time lê. Hoje o `pr` gera título com `[SPEC-NNNN]`, corpo com tabela de specs, gates e emendas, e marcador `<!-- sdd: -->` — tudo proibido no modo privado. Sem instruções, o agente também não sabe que deve escrever commits no padrão do time.

**Objetivos (dentro do escopo):**
- Detecção das convenções do time pelo `git` e pelos arquivos do repositório; bloco `team:` no sdd-config do `spec_root`.
- `pr` em modo privado: título e corpo no padrão do time, `leak-check` antes de imprimir.
- `references/private-mode.md`, parágrafo no `SKILL.md` e menção no README.
- Teste da jornada privada completa.

**Não-objetivos (fora do escopo):**
- Abrir o PR na plataforma (continua com o agente, com autorização do usuário).
- Ajustes do `pr` no modo completo (spec lite própria).
- Distinguir squash de rebase pela plataforma (o `git` só mostra "linear"; o G7 da SPEC-0005 trata os dois).

## 3. Dependências
- **Implementações necessárias:** SPEC-0004 — o `pr` chama o `leak-check`; SPEC-0005 — a jornada completa usa o rastreio sem marcas e o G7 por `patch-id`.
- **Contratos consumidos:** SPEC-0003@1 — modo e `spec_root`.
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. `cmd_pr` (`spec_graph.py:2692`) monta título e corpo a partir das specs; `PR_TEMPLATE_PATHS` (`:2795`) já lista os templates conhecidos por plataforma; a documentação da skill segue o padrão de `references/*.md` citados pelo `SKILL.md`.

**Decisão:** `detect_team_conventions(root)` puro sobre a saída do `git` e a árvore de arquivos; `cmd_pr` ganha um ramo de modo privado que preenche o template do time por título de seção (palavras-chave em português e inglês) ou usa um corpo neutro. A documentação fica num arquivo próprio (`references/private-mode.md`), carregado só quando o modo está ativo — o `SKILL.md` ganha um parágrafo curto.

**Justificativa:** detecção sem chamar plataforma (ADR-0001); o `SKILL.md` continua enxuto para quem só usa o modo completo.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** perguntar as convenções ao usuário a cada init (o `git log` já responde e o usuário corrige no sdd-config); um `SKILL.md` separado para o modo privado (duplicaria o processo — decisão da conversa de 2026-10-14: mesma skill).

**ADRs:** ADR-0006.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** detecção lê no máximo os últimos 200 commits da base; menos de 1 s num repositório de teste com 200 commits (IT-01).
- **Segurança:** o corpo do PR nunca inclui caminhos do `spec_root` nem conteúdo fora das seções mapeadas.
- **Privacidade e dados pessoais:** o PR leva só o que a spec descreve do comportamento (resumo, como testar, riscos) — sem gates, impedimentos ou emendas.
- **Disponibilidade e resiliência:** sem base com histórico (repositório novo) → convenções "desconhecida" e corpo neutro.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** bloco `team:` do sdd-config do `spec_root`, `pr` em modo privado, `private-mode.md`.

```text
private init (e private detect, para refazer) grava no sdd-config do spec_root:
  team:
    merge: merge | linear | desconhecida      (merges com 2 pais ≥ 20% dos commits da base nos últimos 200 → merge; nenhum → linear)
    commits: conventional | livre              (≥ 80% dos últimos 50 assuntos em Conventional Commits → conventional)
    hooks: husky | lefthook | pre-commit | core.hooksPath | nenhum
    pr_template: <caminho> | ""                (primeiro existente: .github/pull_request_template.md, .github/PULL_REQUEST_TEMPLATE.md,
                                                docs/pull_request_template.md, .gitlab/merge_request_templates/Default.md,
                                                .azuredevops/pull_request_template.md)
  saída: "Detectado: <merge> · <commits> · hooks <hooks> · template <caminho|nenhum>"

pr ID [ID ...] [--title] [--out FILE] em modo privado:
  título: commits=conventional → "<tipo>: <título da spec em minúscula inicial>"; livre → "<Título da spec>"; nunca [SPEC-…]
  corpo com pr_template: mantém os títulos e comentários do template; preenche a seção cujo título contém
    resumo|summary|descrição|description|o que|what → Visão Geral + Motivação
    teste|test|como testar|how to test           → testes do plano em linguagem natural (sem IDs)
    risco|risk|rollback|rollout                  → Plano de Rollout
    as demais seções ficam como no template
  corpo sem template: "## O que muda", "## Como testar", "## Riscos e rollback"
  sem marcador <!-- sdd -->, sem tabela de specs, gates, impedimentos, emendas ou rodapé Refs
  antes de imprimir: leak-check sobre título e corpo; achado → exit 1 listando os achados, nada impresso em --out

references/private-mode.md: quando usar; private init/status/off; onde fica o quê; commits e branch no padrão do time;
  o que muda em cada gate (G1 --at, G5 pelo comando ci, G7 por patch-id); leak-check e hook; limites (sem CI do SDD,
  sync e dados do time, atribuição de IA fora do escopo)
SKILL.md: parágrafo "Private mode" — se `status` mostra MODO PRIVADO, ler references/private-mode.md antes de qualquer passo
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. Novo: `references/private-mode.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Convenções detectadas | histórico com merges e Conventional Commits; histórico linear com assuntos livres; `.husky/`; template GitHub | merge/conventional/husky/caminho; linear/livre | UT-01, IT-01 |
| Repositório sem histórico | base vazia | tudo "desconhecida", template "" | UT-01 |
| Título no padrão do time | conventional; livre | `feat: …` sem ID; `Título` sem ID | UT-02 |
| Corpo com template do time | template com "Summary" e "How to test" | seções preenchidas, resto intacto, sem marcas | IT-02 |
| Corpo sem template | nenhum template | corpo neutro de três seções | IT-03 |
| PR com vazamento | spec cujo resumo cita `ADR-0006` | exit 1 com o achado, nada em `--out` | IT-04 |
| Jornada completa | init → new → aprovação → red → green → G1..G4 → pr → squash na base → G7 | nenhum arquivo, mensagem, branch ou PR com marca; spec implementada no spec_root | IT-05 |
| Modo completo | `pr` sem modo privado | igual a hoje | IT-06 |
| Instruções do agente | SKILL.md e private-mode.md | SKILL.md cita o arquivo; o arquivo cobre os tópicos do contrato | UT-03 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o `pr` do modo completo já é fixado por `test_pr_check_ignores_narrative_refs_and_exempts_root_docs` e `test_pr_out_prints_only_the_title`; IT-06 os mantém como guarda.

### 7.2 Testes Unitários
- **UT-01** — Dado listas sintéticas de commits (pais e assuntos) e de arquivos, quando `detect_team_conventions` roda, então devolve `merge/conventional/husky/.github/pull_request_template.md` para um caso, `linear/livre/nenhum/""` para outro e `desconhecida` com histórico vazio.
- **UT-02** — Dado uma spec `type: feature` com título "Suporte a múltiplos cartões", quando o título do PR é montado em modo privado, então dá `feat: suporte a múltiplos cartões` com commits conventional e `Suporte a múltiplos cartões` com commits livres, nunca com "SPEC".
- **UT-03** — Dado o `SKILL.md` e `references/private-mode.md`, quando lidos, então o `SKILL.md` cita `references/private-mode.md` e o arquivo tem as seções do contrato (ativação, onde fica o quê, commits e branch, gates, leak-check, limites).

### 7.3 Testes de Integração
- **IT-01** — Dado um repositório temporário com 200 commits (merges `--no-ff`, assuntos Conventional), `.husky/` e `.github/pull_request_template.md`, quando roda `private init`, então o bloco `team:` no sdd-config do `spec_root` tem merge, conventional, husky e o caminho do template, a saída mostra "Detectado:", e a detecção leva menos de 1 s.
- **IT-02** — Dado o modo privado e um template do time com "## Summary", "## How to test" e "## Checklist", quando roda `pr SPEC-0001 --out pr.md`, então Summary e How to test vêm preenchidos, Checklist fica como no template e `leak-check` sobre o arquivo não acha nada.
- **IT-03** — Dado o modo privado e nenhum template, quando roda `pr SPEC-0001`, então o corpo tem "O que muda", "Como testar", "Riscos e rollback" e nenhuma marca do SDD.
- **IT-04** — Dado o modo privado e uma spec cujo resumo cita `ADR-0006`, quando roda `pr SPEC-0001 --out pr.md`, então sai com 1, lista o achado e `pr.md` não é criado.
- **IT-05** — Dado um repositório "do time" com remoto bare, histórico livre e squash, quando o fluxo inteiro roda pela CLI em modo privado (`private init`, `new`, `set status=approved`, commit de teste, `gate G1 --run`, commit de código, `gate G2..G4 --run`, `pr --out`, squash na base, `gate G7 --run`), então: o repositório não tem `docs/specs`, `docs/adr`, `tools/sdd` nem `.githooks`; `leak-check --range` sobre a base e a branch não acha nada; o corpo do PR não tem marca; e a spec no `spec_root` tem G1, G2, G4 e G7 = PASS, com G7 citando "squash".
- **IT-06** — (guarda: passa antes da mudança) Dado o modo completo, quando roda `pr SPEC-0001`, então título e corpo são os de hoje (com `[SPEC-0001]`, marcador e tabela de gates).

### 7.4 Testes de Contrato
- **CT-01** — Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando os comandos desta spec leem `project.private`, `project.spec_root` e `project.config_path`, então usam esses valores (e não caminhos fixos) — verificado com um registro de teste e um `spec_root` fora do repositório.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração; IT-05 é a jornada privada completa.

### 7.6 Outros
- Tempo da detecção lido no IT-01 (RNF de desempenho).

**Dublês e dados de teste:** repositórios temporários com remoto bare; `test` do sdd-config como na SPEC-0005 (script mínimo, sem stack).

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; só atua em modo privado.
- **Dados/schema:** bloco `team:` novo só no sdd-config do `spec_root`.
- **Compatibilidade:** `pr` do modo completo inalterado (IT-06).
- **Observabilidade:** saída "Detectado:" no init; achados do `leak-check` no `pr`.
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Como o PR segue o padrão do time? — Preenchendo o template de PR do time por título de seção; sem template, corpo neutro de três seções (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)
- [x] As instruções do modo vão no SKILL.md? — Num arquivo próprio (`references/private-mode.md`) carregado só no modo privado, com um parágrafo curto no SKILL.md (decisão da conversa: mesma skill, modo separado; thomas, 2026-10-14)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação

**Fase 1: Convenções do time**
- [ ] Red: UT-01 e CT-01 com a tag `SPEC-0006:<ID>`, IT-01
- [ ] Green: `detect_team_conventions`, bloco `team:` no `private init` e `private detect`

**Fase 2: PR neutro**
- [ ] Red: UT-02, IT-02, IT-03, IT-04; IT-06 (guarda) passando
- [ ] Green: título e corpo no padrão do time, preenchimento do template, leak-check antes de imprimir

**Fase 3: Documentação e jornada**
- [ ] Red: UT-03, IT-05
- [ ] Green: `references/private-mode.md`, parágrafo no `SKILL.md`, README; jornada completa passando
- [ ] Refactor mantendo tudo verde; validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] `SDD_TOOL_VERSION` e CHANGELOG atualizados (ADR-0005)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy: N/A — pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — d96b6d4 | 2026-10-14 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). -->

### O que foi entregue

### Como foi feito

### Prova de Correção

### Verificação
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
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 15. Emendas
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
