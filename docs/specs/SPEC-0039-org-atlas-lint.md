---
id: SPEC-0039
title: "org-atlas: lint do atlas"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: [SPEC-0037@1]
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/maintenance.md, skills/org-atlas/tests/test_lint.py, skills/org-atlas/tests/fixtures/lint/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011, ADR-0012]
external: []
size: S
approved_by:
approved_at:
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0039`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
