---
id: {{id}}
title: {{title}}
tier: epic
type: feature
status: proposed
created: {{created}}
depends_on: []
adrs: []
approved_by:
approved_at:
---

# {{id}} — {{title}} (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: {{id}}`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
{{Resultado de negócio e técnico esperado ao final do épico.}}

## 2. Escopo
**Dentro do escopo:**
- {{O que o épico entrega}}

**Fora do escopo:**
- {{O que fica explicitamente de fora}}

## 3. Arquitetura Alvo
**Contexto:** {{Projeto existente: arquitetura atual (ADRs as-is) e o que muda — se muda, type: migration | Projeto novo: stack e arquitetura definidas nos ADRs de fundação}}

{{Como o sistema fica ao final: módulos, fronteiras, fluxos principais, contratos entre as filhas. Diagrama se ajudar.}}

**Decisões (ADRs):** {{ADR-NNNN — decisão. Toda decisão transversal vira ADR (liste também no frontmatter `adrs`) | N/A}}

**Regras de arquitetura a garantir (G3):** {{ex: Domain não referencia Infrastructure; módulos só se comunicam por contratos públicos — cada regra com o teste de arquitetura que a garante}}

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| {{SPEC-NNNN}} | {{título}} | {{full}} | {{feature}} | {{M}} | {{—}} | {{—}} |

## 5. Estratégia de Entrega
- **Ambientes:** {{ex: staging automático a cada merge; produção via pipeline com aprovação}}
- **Entrega por onda:** {{o que vai para produção ao fim de cada onda e o que fica atrás de feature flag}}
- **Feature flags:** {{nome — o que controla — critério para ligar e para remover | N/A}}
- **Rollback:** {{como reverter cada onda}}
- **Métricas de sucesso pós-release:** {{o que observar e por quanto tempo}}

## 6. Riscos & Mitigações
- {{risco — mitigação | N/A}}

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] {{critério verificável — SPEC-NNNN:E2E-01}}

## 8. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 9. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report {{id}}` ajuda a montar. -->
