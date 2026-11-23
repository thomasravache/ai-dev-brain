---
id: ADR-0024
title: Verificação depois do deploy por foto e comparação, com veredito e nada guardado no atlas
status: accepted
origin: decision
date: 2026-11-22
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes da SPEC-0090 (UT-03 a UT-06, IT-01) e da SPEC-0091 (UT-01)
---

# ADR-0024 — Verificação depois do deploy por foto e comparação, com veredito e nada guardado no atlas

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
Os testes da gluon-spec (unidade, integração com dependências reais e E2E) provam o código antes do merge. Eles não pegam o que só existe no ambiente: variável faltando, permissão, imagem errada no GitOps, erro que aparece com tráfego real. Como o G6 pode dizer se a entrega chegou e está saudável num ambiente, de forma repetível, agnóstica e sem guardar dados de execução no atlas? (SPEC-0075, SPEC-0090)

## Direcionadores da Decisão
- **Evidência, não impressão** (mandato 8 da gluon-spec).
- **Comparar contra o estado de antes,** para separar erro novo de erro antigo.
- **Só leitura, pelas probes** (ADR-0023).
- **Nada de execução no atlas;** a foto é da tarefa.
- **Veredito explícito,** com "não verificado" e o motivo quando falta um dado ou um adaptador.

## Opções Consideradas
- **`atlas.py verify` em duas fases:** `snapshot` antes do merge grava uma foto num arquivo da tarefa; `compare` depois do deploy produz o veredito.
- **Só instruções na gluon-spec,** com o agente montando cada consulta.
- **Análise de canário completa** por métricas (estilo Kayenta ou Flagger) já na primeira entrega.

## Resultado da Decisão
**Opção escolhida:** "`atlas.py verify` em duas fases". É determinística e testável: a mesma foto e o mesmo estado dão o mesmo veredito. Também reaproveita as probes e o mapa de acesso. Instruções sozinhas não são repetíveis. A análise por métricas fica para uma onda seguinte, quando houver um adaptador de métricas.

Regras:
1. **A foto.** Fica num arquivo indicado por quem chama, fora do atlas. Guarda as imagens em execução, as réplicas prontas, os restarts, os eventos de alerta e as assinaturas dos erros dos logs na janela de antes, tudo com redaction.
2. **A comparação.** Confere três coisas:
   - a entrega: a imagem esperada em execução e o rollout concluído;
   - o runtime: réplicas prontas, restarts novos e eventos de alerta novos;
   - os logs: assinaturas de erro novas contra as da foto, numa janela configurável.
3. **O veredito.** É `passou`, `degradou` ou `inconclusivo`. Cada verificação traz a sua evidência, ou "não verificado" com o motivo. Em `degradou`, o comando sugere o rollback e não o executa.
4. **Produção.** Segue o ADR-0023: confirmação a cada execução. A verificação em produção é só passiva.
5. **Limites configuráveis.** Os limites (assinaturas novas toleradas, restarts tolerados, janela) vêm do `sdd-config.yml` do projeto, com padrões conservadores.

### Consequências
- **Boa:** o G6 ganha evidência real do ambiente, e o Relatório de Entrega mostra o que foi verificado e o que não foi.
- **Boa:** uma capacidade nova (métricas, banco, mensageria) entra como mais uma verificação do `compare`, com o seu adaptador.
- **Ruim:** sem foto de antes, as assinaturas antigas não se separam das novas. Nesse caso o veredito dos logs é `inconclusivo`.

### Confirmação (G3)
Os testes da SPEC-0090 falham se o `verify` gravar qualquer coisa no atlas, se der `passou` com uma verificação não feita sem marcá-la, ou se executar uma ação de escrita. Os da SPEC-0091 falham se o G6 descrito na skill deixar de exigir a confirmação de produção.

## Prós e Contras das Opções
| Critério (peso) | `verify` em duas fases | Só instruções | Canário por métricas |
|---|---|---|---|
| Repetível e testável (alto) | sim | não | sim |
| Separa erro novo de antigo (alto) | sim | depende | sim |
| Pronto com o que existe (alto) | sim | sim | não (falta adaptador de métricas) |
| Cobertura de sinais (médio) | estado e logs | depende | métricas completas |

## Mais Informações
- SPEC-0075, SPEC-0086 (roteiro de verificação), SPEC-0088, SPEC-0089, SPEC-0090, SPEC-0091.
- ADR-0023 (probes).
- Inspiração (não verificada como regra): análise de canário (Kayenta, Flagger, Argo Rollouts), golden signals do SRE e quality gates do Keptn.
