---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (decisão nova) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
{{Situação, forças e restrições que exigem a decisão, em 2–3 frases ou como pergunta. as-is: onde o padrão existe hoje e 2–3 arquivos de referência.}}

## Direcionadores da Decisão
- {{ex: time domina a stack; LGPD exige residência no Brasil; p95 < 200ms | as-is: N/A}}

## Opções Consideradas
- {{Opção A}}
- {{Opção B}}
- {{Opção C | as-is: "N/A — padrão existente documentado"}}

## Resultado da Decisão
**Opção escolhida:** {{"Opção A", porque ... (ligada aos direcionadores)}}

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que piora ou fica mais caro}}

### Confirmação (G3)
{{Teste de arquitetura que falha se a decisão for violada (ex: NetArchTest, ArchUnit, dependency-cruiser, import-linter) e onde ele vive | revisão no G4 quando não for verificável por teste | N/A — motivo}}

## Prós e Contras das Opções
<!-- Decisão de tecnologia: matriz com critérios ponderados pelo contexto (references/greenfield.md). as-is: "N/A". -->
{{| Critério (peso) | Opção A | Opção B | Opção C | ... | N/A — padrão existente documentado}}

## Mais Informações
<!-- Fontes oficiais consultadas, versão estável/LTS e janela de suporte, com a data da verificação. Se não foi possível verificar, diga explicitamente. Links para specs relacionadas. -->
{{fonte — o que confirma — data | N/A}}
