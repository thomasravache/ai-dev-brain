---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- status: proposed | accepted | superseded | rejected — vira accepted quando a spec que o introduz é aprovada (H1). origin: decision (decisão nova) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto
{{Situação, forças e restrições que exigem a decisão. Para as-is: onde o padrão existe hoje e 2–3 arquivos de referência.}}

## Opções Avaliadas
<!-- Decisão de tecnologia/arquitetura: 2–3 opções reais pontuadas por critérios ponderados pelo contexto (ver references/greenfield.md). as-is: "N/A — padrão existente documentado". -->
{{| Critério (peso) | Opção A | Opção B | Opção C | ... | N/A — padrão existente documentado}}

## Decisão
{{A decisão, de forma afirmativa e verificável. ex: "O módulo Payments só é acessado via IPaymentsApi."}}

## Consequências
**Positivas:** {{o que melhora}}

**Negativas / trade-offs:** {{o que piora ou fica mais caro}}

## Como é Garantida (G3)
{{Teste de arquitetura que falha se a decisão for violada (ex: NetArchTest, ArchUnit, dependency-cruiser, import-linter) e onde ele vive | N/A — motivo}}

## Fontes
<!-- Decisão de tecnologia: documentação oficial consultada, versão estável/LTS e janela de suporte, com a data da verificação. Se não foi possível verificar, diga explicitamente. -->
{{fonte — o que confirma — data | N/A}}
