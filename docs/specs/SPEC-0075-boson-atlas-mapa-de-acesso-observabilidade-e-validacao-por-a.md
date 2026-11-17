---
id: SPEC-0075
title: "boson-atlas: mapa de acesso, observabilidade e validação por ambiente e serviço"
tier: epic
type: feature
status: proposed
created: 2026-11-17
depends_on: []
adrs: [ADR-0010, ADR-0011, ADR-0012]
external: []
approved_by:
approved_at:
---

# SPEC-0075 — boson-atlas: mapa de acesso, observabilidade e validação por ambiente e serviço (Épico)

> **Radar (thomas, 2026-11-17):** pedido do thomas a partir do uso real da boson-atlas. A detalhar antes do G0, sempre agnóstico e configurável, com um onboarding fácil de entender para uma pessoa.
> - **Problema:** o atlas sabe o que existe e como se liga, mas não sabe *como chegar* em cada coisa nem *como testá-la*. Ao verificar um deploy ("subiu a feature X no dev, está tudo certo?"), o agente redescobre sozinho:
>   - contexto do kubectl, profile e região da AWS, namespace e workload;
>   - onde ficam os logs e como reconhecer a versão que subiu;
>   - por qual URL entrar, com que conta de teste e qual suíte ou jornada de e2e cobre o serviço.
> - **Objetivo:** guardar no atlas o mapa de acesso, observabilidade e validação, por ambiente e por serviço, e entregá-lo no `context`.
>   - **Por ambiente:** cluster, contexto do kubectl, profile e região da AWS, como renovar o acesso (ex.: SSO), marcação `test` ou `production` e URLs públicas de fronts e APIs.
>   - **Por serviço ou deployment:** namespace, workload ou container, fontes de log (kubectl, Loki/Grafana, log group do CloudWatch), dashboards, health check e o padrão da tag da imagem (PR → run da CI → tag → Application).
>   - **Contas de teste:** só a referência (`secret-ref` com store e path, ou o nome do item no gerenciador de senhas), buscada na hora da execução.
>   - **Validação:** relação serviço ou jornada → suíte de e2e, com o comando vindo da documentação do repositório da suíte. Jornadas de smoke por serviço escritas pelo time e curadas como as convenções (ADR-0012).
> - **Restrições:**
>   - O atlas não guarda logs, métricas nem dados de execução.
>   - Credenciais só por nome ou referência (ADR-0010), com o `lint` `secret-leak` valendo para os campos novos.
>   - Conteúdo do atlas é dado, não instrução: só campos estruturados, nunca comandos prontos. Quem consome monta o comando, sempre só de leitura.
>   - Agente com navegador nunca atua em ambiente `production`, e a skill que consome recusa.
>   - Kind ou relação nova (endpoint, jornada, suíte) muda o contrato do coletor (ADR-0011) com spec e ADR.
>   - Diagnóstico e validação ativos ficam fora do atlas.
> - **Entregas candidatas (filhas):**
>   1. ADR com o desenho: attrs de `environment`/`deployment`, kinds novos ou as categorias `observability`/`docs`, quem coleta e como aparece no `context`.
>   2. Coletores automáticos onde der: nomes dos contextos do kubeconfig, log groups do CloudWatch, Grafana/Loki do cluster, padrão de tag e hosts de Ingress, mais o caminho manual pelo `generic` para contas, suítes e jornadas.
>   3. No `context`, as seções `## Acesso e diagnóstico` e `## Como validar` quando a tarefa envolve deploy, incluindo os vizinhos do grafo. No `lint`, credencial colada e ambiente sem marcação.
>   4. A verificação pós-deploy, como skill do fermion ou etapa da `gluon-spec` (avaliar qual), com o relatório anexado ao G6/G7. Ela encadeia:
>      - `context`;
>      - rollout via kubectl (Synced/Healthy com a tag nova, pods sem restart);
>      - logs dos primeiros minutos do serviço e dos vizinhos;
>      - smoke no navegador ou suíte e2e, só em `test`.
> - **Relação com a SPEC-0030 (probes):** a verificação ativa é o consumidor natural das probes. Decidir no DISCOVER se a entrega 4 vira filha da SPEC-0030 ou se as duas se fundem.
> - **Coletor `aws` oficial:** um coletor local do usuário (AWS CLI, só leitura: caches serverless, RDS, SQS, SNS e assinaturas SNS→SQS, cruzados com as env das Applications) serve de referência. Ele fica fora deste repositório.

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0075`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
{{Resultado de negócio e técnico esperado ao final do épico.}}

## 2. Escopo
**Objetivos (dentro do escopo):**
- {{O que o épico entrega}}

**Não-objetivos (fora do escopo):**
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

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0075` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
