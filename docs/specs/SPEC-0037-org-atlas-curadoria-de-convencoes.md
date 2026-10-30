---
id: SPEC-0037
title: "org-atlas: curadoria de convenções"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/curation.md, skills/org-atlas/assets/pages/convention.md, skills/org-atlas/assets/atlas-config.yml, skills/org-atlas/tests/test_curate.py, skills/org-atlas/tests/fixtures/curate/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0012]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0037 — org-atlas: curadoria de convenções

## 1. Visão Geral
Implementa a curadoria do ADR-0012. A partir dos sinais dos coletores (padrão de título de PR, prefixo de branch, forma de merge, template de PR), o `atlas.py` **propõe** convenções como `inferred`, com a evidência. Só um humano, pelo `curate confirm` ou `curate reject`, muda o status. Só convenção `confirmed` vale como regra para outras skills.

## 2. Motivação & Escopo
**Motivação:** inferir não é normatizar. Sem curadoria, a bagunça de metade dos PRs vira padrão e as outras skills passam a seguir isso (SPEC-0029, ADR-0012).

**Objetivos (dentro do escopo):**
- `curate propose`, que também roda no fim de todo `scan`: cria ou atualiza `conventions/<id>.md` com `status: inferred` quando um padrão domina (padrão: pelo menos 60% de pelo menos 20 itens; configurável em `curation`).
- `curate list [--status S] [--json]`, `curate confirm ID --by NOME --via VIA` e `curate reject ID --by NOME --via VIA [--reason TEXTO]`.
- Escopo da convenção: `organization` quando a maioria dos repositórios com sinal segue o mesmo padrão; senão, uma por `repository`.
- Evidência numa região gerada; texto do time no arquivo preservado.

**Não-objetivos (fora do escopo):**
- Convenções de código (estrutura de pastas, estilo): precisam de coletores que leiam código, fora do MVP.
- Aplicar a convenção em algum lugar: isso é das skills consumidoras (ex.: `gh-create-pr`, `sdd-management`).

## 3. Dependências
- **Implementações necessárias:** SPEC-0036 — as páginas geradas e as regras de região que os arquivos de convenção reaproveitam.
- **Contratos consumidos:** N/A.
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** segue as regiões geradas da SPEC-0036 e o padrão de "o script cria, o humano decide" do H1 da `sdd-management` (`set ... approved_by`), que aqui vira `confirmed_by` e `confirmed_via`.

**Decisão:** o id da convenção inclui o padrão dominante (ex.: `pr-title-conventional`, `merge-method-merge`). Se o padrão dominante muda, é outra convenção; uma convenção `rejected` nunca é proposta de novo com o mesmo id, mas a evidência dela continua atualizada.

**Justificativa:** id estável e ligado ao padrão resolve o "não propor de novo o que foi rejeitado" sem regra de limiar difícil de explicar.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** confirmação automática por limiar (ADR-0012, opção B).

**ADRs:** ADR-0010, ADR-0012.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `propose` com sinais de 300 repositórios em menos de 2 s.
- **Segurança:** nenhum comando além de `confirm`/`reject` grava `confirmed`/`rejected` (UT-04).
- **Privacidade e dados pessoais:** a evidência guarda contagens e a amostra já mascarada pelo `scan`; nenhum autor de PR.
- **Disponibilidade e resiliência:** sinal ausente para uma categoria → nenhuma proposta, sem erro.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comandos `curate`, chave `curation` e o formato dos arquivos de convenção (consumido pela SPEC-0038 e pela SPEC-0039).

```text
atlas-config.yml:
  curation: {min_share: 0.6, min_total: 20}

conventions/<id>.md (contrato v1, references/curation.md):
  ---
  id: pr-title-conventional
  title: "Títulos de PR em Conventional Commits"
  kind: pr-title | branch-prefix | merge-method | pr-template
  scope: organization | repository:<org>/<nome>
  status: inferred | confirmed | rejected
  proposed_at: AAAA-MM-DD
  confirmed_by:            # preenchido só por confirm/reject
  confirmed_at:
  confirmed_via:           # "PR #n" | "local"
  reason:                  # só em reject, opcional
  ---
  <!-- atlas:begin evidence --> total, quantos seguem, porcentagem, repositórios, amostra <!-- atlas:end evidence -->
  ## Notas  (texto do time, nunca reescrito)

atlas.py curate propose [--json]      (também roda no fim do scan)
  imprime "N nova(s), M atualizada(s), K esperando decisão"
atlas.py curate list [--status inferred|confirmed|rejected] [--json]
atlas.py curate confirm ID --by NOME --via "PR #n"|local
atlas.py curate reject  ID --by NOME --via "PR #n"|local [--reason TEXTO]
  sem --by ou --via: exit 2 "confirm exige --by e --via"
  id inexistente: exit 2 "convenção não encontrada: ID"
  --via fora do formato: exit 2 "--via aceita 'PR #<n>' ou 'local'"
  convenção já confirmada ou rejeitada: exit 2 "convenção já está <status>"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Padrão dominante | ≥ 60% de ≥ 20 itens | convenção `inferred` com evidência | UT-01, IT-01 |
| Sem padrão | abaixo do limiar ou poucos itens | nenhuma proposta | UT-01 |
| Escopo | maioria dos repositórios com o mesmo padrão | `scope: organization`; senão por repositório | UT-02 |
| Confirmar | `confirm` com `--by` e `--via` | `status: confirmed` com quem, quando e por onde | IT-02, CT-01 |
| Confirmar sem dados | sem `--by` ou `--via`, `--via` inválido | exit 2 | UT-03 |
| Só humano confirma | `propose` e `scan` | nunca gravam `confirmed` nem `rejected` | UT-04, IT-02 |
| Rejeitada | `reject` e um novo scan | não volta a ser proposta; evidência atualizada | IT-03 |
| Texto do time | notas fora da região | preservadas | IT-04 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado sinais com 70% de títulos em Conventional Commits em 50 PRs, e outros com 40% ou com 10 PRs, quando as propostas são calculadas, então só o primeiro vira convenção.
- **UT-02** — Dado sinais de 5 repositórios, 4 com o mesmo padrão, quando o escopo é decidido, então a convenção é `organization`; com 2 de 5, uma por repositório.
- **UT-03** — Dado `confirm` sem `--by`, sem `--via` ou com `--via` inválido, quando os argumentos são validados, então sai com 2 e a mensagem do contrato.
- **UT-04** — Dado o código do `atlas.py`, quando se procura quem grava `status: confirmed` ou `rejected`, então só as funções de `confirm` e `reject` gravam.

### 7.3 Testes de Integração
- **IT-01** — `scan` pela CLI com coletor falso devolvendo sinais de PR cria `conventions/pr-title-conventional.md` com `status: inferred` e a evidência.
- **IT-02** — `curate confirm pr-title-conventional --by thomas --via "PR #3"` grava `confirmed`, `confirmed_by`, `confirmed_at` e `confirmed_via`; um novo `scan` mantém `confirmed`.
- **IT-03** — Depois de `curate reject`, um novo `scan` com os mesmos sinais não cria outra proposta com o mesmo id e atualiza só a evidência.
- **IT-04** — Uma nota escrita na convenção continua igual depois de um novo `scan`.

### 7.4 Testes de Contrato
- **CT-01** — Os arquivos de convenção gerados nos testes seguem o formato de `references/curation.md` (chaves, valores permitidos, região `evidence`), contrato consumido pela SPEC-0038 e pela SPEC-0039.

### 7.5 Testes E2E
- N/A — comando usado pelo agente; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** fixtures de sinais e coletor falso.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** `conventions/` com contrato v1.
- **Compatibilidade:** N/A — formato novo.
- **Observabilidade:** resumo do `curate propose` no fim do scan.
- **Rollback:** reverter o PR; convenções são arquivos versionados no git do atlas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Quem confirma uma convenção — quem aprova o PR do atlas (modo repositório) ou quem roda o `curate` (modo local) (thomas, 2026-10-30)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 80ff4f8 (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0037`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
