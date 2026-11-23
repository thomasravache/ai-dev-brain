---
id: SPEC-0091
title: "gluon-spec: verificação ativa no G6 com atlas.py verify"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-22
parent: SPEC-0075
depends_on: [SPEC-0090]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/gluon-spec/SKILL.md, skills/gluon-spec/references/gates.md, skills/gluon-spec/references/sdd-config.template.yml, skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0024]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0091 — gluon-spec: verificação ativa no G6 com atlas.py verify

> Origem: épico SPEC-0075. Thomas pediu em 2026-11-20 que, depois do PR, a gluon-spec acompanhe o deploy e os logs do ambiente, além dos testes.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O G6 da gluon-spec passa a usar o `atlas.py verify` (SPEC-0090) para provar que a entrega chegou e está saudável em cada ambiente configurado:
- **antes do merge:** tira a foto do ambiente;
- **depois do deploy:** compara o estado com a foto e registra o veredito e as evidências no Relatório de Entrega.

Tudo é opcional e configurável em `delivery_check`.

## 2. Motivação & Escopo
**Motivação:** a SPEC-0086 deu ao G6 o roteiro de onde olhar. Falta olhar de fato, com evidência repetível, e saber se apareceram erros novos.

**Objetivos (dentro do escopo):**
- **`delivery_check` no `sdd-config.yml`:** ganha `verify` (padrão `false`), `window_minutes` (10), `max_new_errors` (0) e `max_new_restarts` (0).
- **Antes do merge, depois do H2:** com `verify: true`, a skill tira a foto de cada serviço da spec em cada ambiente de `delivery_check.environments`. A foto fica num arquivo temporário da tarefa, fora do repositório e do atlas.
- **Depois do deploy:** com os passos 1 e 2 do roteiro concluídos (pipeline e imagem nova no repositório de configuração), a skill espera a janela, roda `verify compare` com a imagem esperada e registra o veredito.
- **G6 pelo veredito:**
  - `passou` → PASS;
  - `degradou` → FAIL, com a sugestão de rollback para a pessoa decidir;
  - `inconclusivo` → a pessoa decide, e a decisão fica registrada.
- **Produção:** cada execução pede confirmação, e lá a verificação é só passiva.
- **Limpeza:** a foto é apagada no fim da tarefa.

**Não-objetivos (fora do escopo):**
- Executar rollback ou qualquer ação: fica com a pessoa.
- Smoke e E2E no ambiente: continuam pelo `smoke_test` e pelo `test_e2e` de hoje.
- Métricas, banco e mensageria: ondas seguintes do épico.

## 3. Dependências
- **Implementações necessárias:** SPEC-0090. O CT-01 confere as opções citadas no G6 contra o `atlas.py verify` real.
- **Contratos consumidos:** N/A (o contrato `verify@1` vem com a implementação da SPEC-0090). Esta spec usa os subcomandos `verify snapshot` e `verify compare`, o veredito e os exits 0, 1, 4 e 5.
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **roteiro de verificação do G6:** SPEC-0086, em `references/gates.md` ("Verification route from the atlas");
- **uso do `org_context`:** SPEC-0081;
- **testes de texto da skill e do template:** `skills/gluon-spec/tests/test_delivery_check.py`.

**Decisão:** a verificação ativa é uma extensão do roteiro da SPEC-0086. Ela usa as mesmas condições (atlas disponível, `delivery_check` ligado), mais `verify: true`. A SKILL.md ganha uma frase e o ponteiro, e as regras ficam no `gates.md`.

**Justificativa:** o comando determinístico (SPEC-0090) faz o trabalho, e a skill só orquestra e registra. Assim a skill segue concisa e agnóstica.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **Verificação ligada por padrão:** exige probes configuradas, e um projeto sem elas teria um G6 sempre inconclusivo.
- **Foto no repositório do projeto:** guardaria dado de execução versionado.

**ADRs:** ADR-0024.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a espera segue a janela configurada, e o `compare` pode ser repetido uma vez depois da janela quando o rollout ainda não terminou.
- **Segurança:** as regras do ADR-0023 valem: só leitura, produção confirmada e nenhum comando vindo do atlas.
- **Privacidade e dados pessoais:** a foto é apagada no fim da tarefa e nunca entra em commit.
- **Disponibilidade e resiliência:** probes desligadas, sem acesso ou sem atlas → a skill registra "verificação ativa não executada: <motivo>" e segue o caminho de hoje (`smoke_test`, `test_e2e`), sem bloquear o G6 por falta de configuração.
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chaves novas de `delivery_check`, o passo de verificação ativa no G6 e o registro no Relatório de Entrega.

```text
sdd-config.yml
  delivery_check:
    enabled: true          # SPEC-0086
    environments: []       # SPEC-0086
    verify: false          # true: verificação ativa com atlas.py verify (exige probes ligadas na máquina)
    window_minutes: 10     # janela de observação depois do deploy
    max_new_errors: 0      # assinaturas de erro novas toleradas
    max_new_restarts: 0    # restarts novos tolerados

G6, com delivery_check.verify true e o atlas disponível (regras do org_context):
  antes do merge (depois do H2), por serviço da spec e ambiente:
    atlas.py verify snapshot --service <s> --env <a> --out <arquivo temporário da tarefa> [--atlas <org_context>]
  depois do deploy, com os passos 1 e 2 do roteiro (SPEC-0086) concluídos, após window_minutes:
    atlas.py verify compare --service <s> --env <a> --baseline <arquivo> --expect-image <imagem do merge>
      --window <window_minutes>m --max-new-errors <n> --max-new-restarts <n> --json
  ambiente de produção (tier production ou sem tier): só com o "sim" da pessoa para aquela execução,
    passando --confirm-production
  veredito → G6:
    passou (0) → evidência PASS com o veredito por ambiente
    degradou (1) → G6 FAIL com as verificações failed e a sugestão de rollback; a decisão é da pessoa
    inconclusivo (5) → a pessoa decide PASS ou FAIL; registrar a decisão e os not_verified
    recusado (4) ou probes indisponíveis → "verificação ativa não executada: <motivo>"; segue smoke/E2E
  Relatório de Entrega ("Deploy"): uma linha por serviço e ambiente com veredito, imagem esperada e as
    verificações (ok, failed, not_verified com motivo)
  o arquivo da foto é apagado no fim da tarefa; nunca entra em commit
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `skills/gluon-spec/SKILL.md`: uma frase no passo 7 e o ponteiro.
- `skills/gluon-spec/references/gates.md`: a subseção "Active verification (SPEC-0091)" no G6.
- `skills/gluon-spec/references/sdd-config.template.yml`: as chaves novas de `delivery_check`, comentadas.
- `SDD_TOOL_VERSION` no `spec_graph.py`, CHANGELOG, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Template | `delivery_check` | `verify`, `window_minutes`, `max_new_errors` e `max_new_restarts` com padrões e comentário; `whats-new` lista | UT-01 |
| Fases | gates.md G6 | foto antes do merge, compare depois do roteiro e da janela, com os comandos do contrato | UT-02 |
| Veredito | gates.md G6 | passou → PASS, degradou → FAIL e a pessoa decide o rollback, inconclusivo → a pessoa decide | UT-02 |
| Produção | gates.md G6 | confirmação por execução, só passiva | UT-03 |
| Indisponível | probes desligadas, sem acesso, sem atlas | "não executada" com o motivo, sem bloquear | UT-03 |
| Foto | gates.md G6 | temporária, apagada no fim, nunca em commit | UT-03 |
| SKILL.md | passo 7 | frase curta e ponteiro para gates.md | UT-04 |
| Sem verify | `verify: false` ou ausente | G6 igual ao da SPEC-0086 | CH-01 |
| Contrato | opções, exits e vereditos citados | iguais aos do `atlas.py verify` | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dados o `gates.md`, a SKILL.md e o template de hoje, então tudo o que a SPEC-0086 fixou (roteiro, "último visto pelo atlas", fallback) continua presente. Sem `verify`, nenhuma instrução nova é exigida (guarda: os testes da SPEC-0086 passam antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — O `sdd-config.template.yml` tem, em `delivery_check`, `verify: false`, `window_minutes: 10`, `max_new_errors: 0` e `max_new_restarts: 0`, cada uma com comentário, e o `whats-new` de um projeto sem elas as lista.
- **UT-02** — O G6 do `gates.md` descreve:
  - o `verify snapshot` antes do merge, depois do H2;
  - o `verify compare` depois dos passos 1 e 2 do roteiro e da janela, com `--expect-image`, `--baseline` e os limites;
  - o mapeamento passou → PASS, degradou → FAIL com o rollback decidido pela pessoa, e inconclusivo → a pessoa decide e a decisão é registrada.
- **UT-03** — O G6 do `gates.md` descreve:
  - a confirmação de produção por execução, com `--confirm-production` só depois do "sim";
  - a verificação só passiva em produção;
  - "verificação ativa não executada: <motivo>" sem bloquear, quando faltam probes, acesso ou atlas;
  - a foto temporária, apagada no fim e nunca em commit.
- **UT-04** — O passo 7 da SKILL.md menciona `delivery_check.verify` e `atlas.py verify` numa frase e aponta para `references/gates.md` (G6). As regras detalhadas não são repetidas na SKILL.md.

### 7.3 Testes de Integração
- N/A — a spec só muda instruções e configuração. Os comandos que ela orquestra são testados de ponta a ponta no IT-01 da SPEC-0090.

### 7.4 Testes de Contrato
- **CT-01** — Toda opção de `atlas.py verify snapshot` e `verify compare` citada no G6 do `gates.md` existe no `--help` do `atlas.py` da boson-atlas. Os exits citados (0, 1, 4 e 5) e os vereditos são os de `skills/boson-atlas/references/verify.md`.

### 7.5 Testes E2E
- N/A — sem jornada interativa própria.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** os arquivos da skill e um projeto temporário para o `whats-new`.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/gluon-spec/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. A verificação vem desligada (`verify: false`).
- **Dados/schema:** chaves opcionais novas no `sdd-config.yml`.
- **Compatibilidade:** um projeto sem as chaves fica igual (CH-01).
- **Observabilidade:** o veredito e as evidências no Relatório de Entrega.
- **Rollback:** `verify: false` ou reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] A verificação ativa vem ligada? — Não. `verify: false` por padrão, porque exige probes e acesso configurados na máquina (recomendação do arquiteto; revisável no H1).
- [x] `inconclusivo` reprova o G6? — Não automaticamente. A pessoa decide e a decisão fica registrada, porque falta de dado não é falha da entrega (recomendação do arquiteto; revisável no H1).

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
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0091`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
