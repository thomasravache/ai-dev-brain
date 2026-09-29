---
id: {{id}}
title: {{title}}
tier: full
type: feature
user_facing: true
status: proposed
created: {{created}}
parent:
depends_on: []
consumes_contract: []
contract_version: 1
touches: []
adrs: []
external: []
size: M
approved_by:
approved_at:
---

# {{id}} — {{title}}

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
{{Descrição curta da funcionalidade e do seu impacto no sistema e no usuário.}}

## 2. Motivação & Escopo
**Motivação:** {{Por que essa mudança é necessária? Qual problema resolve ou que valor agrega?}}

**Objetivos (dentro do escopo):**
- {{O que será entregue nesta spec}}

**Não-objetivos (fora do escopo):**
- {{O que explicitamente NÃO será feito — itens que poderiam ser assumidos mas não serão}}

## 3. Dependências
<!-- As dependências entre specs ficam no frontmatter. Use `depends_on` só quando a IMPLEMENTAÇÃO da outra spec for necessária; se bastar o CONTRATO, use `consumes_contract` (permite rodar em paralelo). -->
- **Implementações necessárias:** {{SPEC-NNNN — por que precisa estar implementada | N/A}}
- **Contratos consumidos:** {{SPEC-NNNN@versão — o que é usado do contrato | N/A}}
- **Pré-requisitos externos:** {{pacotes, serviços, infraestrutura, feature flags | N/A}}

## 4. Decisão Arquitetural
<!-- Projeto existente: o padrão atual é lei. Qualquer desvio (lib, framework, camada, padrão ou convenção nova) só com type: migration ou ADR aprovado. -->
**Contexto:** {{Projeto existente: padrão atual seguido e arquivos de referência (ex: "segue src/Orders/CreateOrder/*") | Projeto novo: padrão definido nos ADRs de fundação}}

**Decisão:** {{ex: novo slice no módulo Payments seguindo o padrão Command/Handler existente}}

**Justificativa:** {{por que se encaixa no contexto descoberto no DISCOVER e nos ADRs aceitos}}

**Desvio do padrão existente:** {{Nenhum | descreva o desvio e o ADR que o aprova}}

**Alternativas descartadas:** {{o que foi considerado e por que foi rejeitado}}

**ADRs:** {{ADR-NNNN aplicados ou criados por esta spec (liste também no frontmatter `adrs`) | N/A}}

## 5. Requisitos Não-Funcionais
<!-- Preocupações transversais de design doc. Não omita linhas: cada uma tem requisito + como será medido, ou "N/A — motivo". -->
- **Desempenho e escala:** {{ex: p95 < 200ms a 100 req/s — teste de carga no staging | N/A — motivo}}
- **Segurança:** {{authN/authZ, validação de entrada, riscos OWASP relevantes — como será verificado | N/A — motivo}}
- **Privacidade e dados pessoais:** {{LGPD/GDPR: dados coletados, base legal, retenção, mascaramento em logs | N/A — motivo}}
- **Disponibilidade e resiliência:** {{timeouts, retries, idempotência, degradação | N/A — motivo}}
- **Acessibilidade (UI):** {{WCAG 2.2 AA nas telas afetadas — verificação com axe/Lighthouse | N/A — motivo}}
- **Custo:** {{impacto em infraestrutura/serviços pagos | N/A — motivo}}

## 6. Artefato A — Contrato
**Interface:** `{{ex: POST /api/v1/cards | evento CardAdded | ICardService.AddAsync | tela /carteira}}`

```text
{{Especificação no formato idiomático do projeto (OpenAPI, AsyncAPI, Proto, assinaturas, schema, fluxo de tela). Inclua entrada, resposta de sucesso e todos os erros.}}
```

**Arquivos/módulos afetados:** ver `touches` no frontmatter. {{Detalhe arquivos a criar/alterar se ajudar o implementador | N/A}}

### 6.1 Mapa de Comportamentos
<!-- Uma linha por comportamento observável (sucesso e cada erro). Toda linha referencia ao menos um teste da seção 7 — o G0 verifica. -->
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| {{Sucesso}} | {{entrada válida}} | {{ex: 201 + corpo; cartão aparece na carteira}} | {{UT-01, IT-01, E2E-01}} |
| {{Erro de validação}} | {{entrada inválida}} | {{ex: 400 + código CARD_INVALID; mensagem no formulário}} | {{UT-02}} |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `{{id}}:<ID>` — o G1 (`spec_graph.py verify`) verifica. Categoria sem testes: "N/A — motivo" SEM ID. Teste que protege comportamento existente e passa antes da mudança: marque `(guarda: passa antes da mudança)`. Estratégia completa: references/testing.md da skill. -->

### 7.1 Testes de Caracterização
<!-- Projeto existente sem cobertura na área alterada: CH-xx fixam o comportamento atual e PASSAM antes da mudança. -->
- {{CH-01 — comportamento atual que deve ser preservado | N/A — área já coberta por testes ou projeto novo}}

### 7.2 Testes Unitários
- **UT-01** — Dado {{contexto}}, quando {{ação}}, então {{resultado}}.
- **UT-02** — Dado {{contexto inválido}}, quando {{ação}}, então {{erro/exceção}}.

### 7.3 Testes de Integração
<!-- Com as dependências reais (containers/emuladores), não mocks. -->
- **IT-01** — {{fluxo principal com infraestrutura real: persistência, mensageria, chamadas externas}}.

### 7.4 Testes de Contrato
<!-- Obrigatório (CT-xx) se esta spec consome contrato de outra ou se outra spec consome o contrato desta. -->
- {{CT-01 — verificação do contrato fornecido/consumido | N/A — não há contrato entre specs}}

### 7.5 Testes E2E
<!-- Obrigatório (E2E-xx) quando user_facing: true: jornada nova ou atualização do E2E que já cobre a jornada. Poucos e significativos. -->
- {{E2E-01 — jornada do usuário: passos e resultado visível | N/A — user_facing: false}}

### 7.6 Outros
- {{performance, segurança, acessibilidade exigidos pelos RNFs — ferramenta e critério | N/A}}

**Dublês e dados de teste:** {{ex: stub do contrato SPEC-NNNN@1, builders de Cartão, dados isolados por teste | N/A}}

**Ambiente de execução:** {{onde IT e E2E rodam: docker compose local, containers no CI, staging}}

## 8. Plano de Rollout
- **Estratégia:** {{deploy direto | feature flag `nome` | canário | blue-green}}
- **Dados/schema:** {{migração expand → migrate → contract, reversível | N/A}}
- **Compatibilidade:** {{versões de API, clientes antigos, contratos publicados | N/A}}
- **Observabilidade:** {{logs, métricas, alertas e dashboards novos ou ajustados}}
- **Rollback:** {{como reverter, em quanto tempo e quem decide}}
- **Etapas de migração/coexistência:** {{type migration: strangler/branch by abstraction, critérios de virada e remoção do caminho antigo | N/A}}

## 9. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
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
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted {{id}}`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
