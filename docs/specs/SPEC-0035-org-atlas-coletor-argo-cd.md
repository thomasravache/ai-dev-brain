---
id: SPEC-0035
title: "org-atlas: coletor Argo CD"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0032]
consumes_contract: [SPEC-0033@1]
contract_version: 1
touches: [skills/org-atlas/assets/collectors/argocd.py, skills/org-atlas/references/collectors/argocd.md, skills/org-atlas/tests/test_collector_argocd.py, skills/org-atlas/tests/fixtures/argocd/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0035 — org-atlas: coletor Argo CD

## 1. Visão Geral
Entrega o coletor `argocd` (categoria `delivery`). Ele lê as Applications do Argo CD e devolve, no contrato do ADR-0011, o que roda onde:
- deployments, serviços, ambientes e clusters;
- de qual repositório cada deployment vem;
- as **referências de configuração**: nomes de chaves e hosts que aparecem nos valores do Helm e nos parâmetros.

As referências de configuração são a matéria-prima para o cruzamento (SPEC-0036) descobrir quem usa qual banco, fila ou serviço.

## 2. Motivação & Escopo
**Motivação:** a entrega é a ponte entre o código e o que roda. Com ela, o atlas liga o repositório ao deployment, o deployment ao ambiente e, pelas configurações, o serviço às suas dependências: a peça que nenhum dev sozinho tem na cabeça.

**Objetivos (dentro do escopo):**
- `argocd.py --from argocd|kubectl [--env-label CHAVE] [--service-label CHAVE] [--input ARQUIVO]`.
- `--from argocd`: `argocd app list -o json`; `--from kubectl`: `kubectl get applications.argoproj.io -A -o json`.
- Entidades `deployment`, `service`, `environment`, `cluster`; relações `deploys`, `runs_in`, `sourced_from`.
- `attrs.config_refs` do deployment: pares `CHAVE=host` extraídos de valores e parâmetros cujas chaves terminam em `_HOST`, `_URL`, `_DSN`, `_ADDR`, `_QUEUE`, `_TOPIC` ou `_BUCKET` (lista configurável), só com o host ou o nome do recurso. Usuário, senha, caminho e query de URLs são removidos pelo próprio coletor antes de sair.
- Guia `references/collectors/argocd.md`: permissões só de leitura (projeto/role de leitura), as duas formas de acesso e o que é extraído.

**Não-objetivos (fora do escopo):**
- Flux e outras ferramentas de entrega: entram depois (SPEC-0029).
- Ler manifestos renderizados, Secrets ou estado do cluster além das Applications (isso é runtime, fase 2, e probes, SPEC-0030).
- Decidir a direção da dependência (leitura ou escrita): o cruzamento marca como `depends_on` inferido.

## 3. Dependências
- **Implementações necessárias:** SPEC-0032 — estrutura de testes e checadores de arquitetura.
- **Contratos consumidos:** SPEC-0033@1 — formato da saída do coletor.
- **Pré-requisitos externos:** `argocd` ou `kubectl` com acesso de leitura às Applications (só no uso real; testes usam `--input` e executáveis falsos).

## 4. Decisão Arquitetural
**Contexto:** mesmo padrão dos coletores da SPEC-0034: script único só com a biblioteca padrão, que chama a CLI do provedor por `subprocess` e tem `--input` para testes.

**Decisão:** o serviço de um deployment vem do label `--service-label` (padrão `app.kubernetes.io/part-of`) ou, sem ele, do nome da Application; o ambiente vem do label `--env-label` (padrão `env`) ou, sem ele, do namespace de destino. A higiene de URL (tirar credencial, caminho e query) acontece no coletor, antes da redaction do `scan`: defesa em duas camadas.

**Justificativa:** labels são o jeito mais comum de agrupar Applications, e o fallback por nome e namespace funciona sem convenção nenhuma.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** ler o repositório GitOps direto (exigiria parser de YAML completo e de Helm); guardar os valores inteiros do Helm (risco alto de segredo e dado demais).

**ADRs:** ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** 1.000 Applications processadas em menos de 10 s depois da resposta da CLI (fixture gerada).
- **Segurança:** só leitura; nada de Secrets; URLs sem credencial já na saída do coletor (UT-03).
- **Privacidade e dados pessoais:** só nomes de chave e hosts saem; nenhum valor de configuração inteiro.
- **Disponibilidade e resiliência:** CLI ausente, sem acesso ou resposta inválida → exit 1 com mensagem clara.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** `argocd.py` (argumentos, saída no contrato do ADR-0011, códigos de saída).

```text
argocd.py --from argocd|kubectl [--env-label env] [--service-label app.kubernetes.io/part-of]
          [--ref-suffixes _HOST,_URL,_DSN,_ADDR,_QUEUE,_TOPIC,_BUCKET] [--input ARQUIVO]
  entidades: deployment:<app> {project, namespace, sync_status, health_status, config_refs: ["CHAVE=host", ...]}
             service:<serviço>   environment:<ambiente>   cluster:<servidor ou nome>
  relações:  deployment → service (deploys); deployment → environment (runs_in); deployment → cluster (runs_in)
             deployment → repository:<owner>/<repo> (sourced_from), quando repoURL é de um provedor reconhecível
  config_refs: valores de spec.source.helm.parameters, helm.values / valuesObject e plugin env cujas chaves
             terminam num sufixo da lista; URL → só o host; credencial, caminho e query removidos
  --input ARQUIVO: lê a lista de Applications em JSON em vez de chamar a CLI
  CLI não encontrada: exit 1 "<argocd|kubectl> não encontrado — veja references/collectors/argocd.md"
  sem acesso: exit 1 "sem acesso às Applications"; resposta inválida: exit 1 "resposta inválida da CLI"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Applications | lista de Applications | deployments, serviços, ambientes e clusters | UT-01, IT-01 |
| Serviço e ambiente | com e sem labels | label quando existe; senão nome e namespace | UT-02 |
| Referências | valores com URL com senha, host simples e chave fora da lista | só `CHAVE=host` das chaves da lista; sem credencial | UT-03 |
| Repositório de origem | repoURL do GitHub | `sourced_from` com `repository:<owner>/<repo>` | UT-04, IT-01 |
| Pela CLI | `argocd` e `kubectl` falsos no PATH | mesma saída que com `--input` | IT-02, CT-01 |
| Sem acesso | CLI falsa falhando | exit 1 com a mensagem | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — coletor novo.

### 7.2 Testes Unitários
- **UT-01** — Dado uma Application, quando é mapeada, então gera `deployment`, `service`, `environment` e `cluster` com as relações `deploys` e `runs_in`.
- **UT-02** — Dado Applications com e sem os labels configurados, quando serviço e ambiente são derivados, então usam o label quando existe e o nome ou o namespace quando não.
- **UT-03** — Dado valores com `DB_URL=postgres://user:senha@db.interno:5432/app?ssl=true`, `CACHE_HOST=redis.interno` e `LOG_LEVEL=debug`, quando as referências são extraídas, então saem só `DB_URL=db.interno` e `CACHE_HOST=redis.interno`.
- **UT-04** — Dado `repoURL` `https://github.com/acme/api.git` e `git@github.com:acme/api.git`, quando a origem é mapeada, então ambos viram `repository:acme/api`.

### 7.3 Testes de Integração
- **IT-01** — `argocd.py --input` com as fixtures de um cluster de exemplo gera a saída esperada.
- **IT-02** — Com `argocd` e `kubectl` falsos no `PATH`, `--from argocd` e `--from kubectl` geram a mesma saída que `--input`.
- **IT-03** — Com a CLI falsa falhando o acesso, o coletor sai com 1 e a mensagem do contrato.

### 7.4 Testes de Contrato
- **CT-01** — A saída de `argocd.py` (fixtures) passa no `validate_collector_output` da SPEC-0033@1, e o `scan` de um atlas com o coletor declarado termina com OK.

### 7.5 Testes E2E
- N/A — coletor chamado pelo `scan`; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** fixtures gravadas de Applications de um cluster fictício e CLIs falsas em Python no `PATH`.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto; o coletor só roda quando declarado.
- **Dados/schema:** N/A.
- **Compatibilidade:** contrato `org-atlas/collector@1`.
- **Observabilidade:** relatório do `scan`.
- **Rollback:** remover o coletor do `atlas-config.yml` ou reverter o PR.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Provedor de entrega do MVP — Argo CD; Flux entra depois (thomas, 2026-10-30)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0035`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
