---
id: SPEC-0011
title: "Documentos vivos: guia de jornadas e mapa do sistema"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-26
parent:
depends_on: []
consumes_contract: [SPEC-0003@1]
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/references/template-journeys.md, skills/sdd-management/references/template-system-map.md, skills/sdd-management/references/template-full.md, skills/sdd-management/references/gates.md, skills/sdd-management/references/greenfield.md, skills/sdd-management/references/brownfield.md, skills/sdd-management/references/sdd-config.template.yml, skills/sdd-management/references/private-mode.md, skills/sdd-management/SKILL.md, README.md, CHANGELOG.md]
adrs: [ADR-0001, ADR-0002, ADR-0006]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-26
---

# SPEC-0011 — Documentos vivos: guia de jornadas e mapa do sistema

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
A skill ganha dois **documentos vivos** por projeto, escritos para pessoas: o **guia de jornadas** (o que cada perfil de usuário faz, passo a passo, como reproduzir localmente e qual teste prova cada passo) e o **mapa do sistema** (o que roda onde, por camada, como sobe localmente e como chega em produção, e qual ADR justifica cada escolha). Eles nascem na fundação (greenfield) ou no baseline de adoção (brownfield), entram na Definição de Pronto do G7 e o `validate` avisa quando ficam para trás das jornadas críticas e dos ADRs aceitos.

## 2. Motivação & Escopo
**Motivação:** a skill registra bem o histórico (specs, ADRs, relatórios de entrega, CHANGELOG), mas não produz uma visão do sistema **como ele está hoje**. Quem chega ao projeto teria de ler dezenas de specs para entender o produto e a infraestrutura. No projeto `subsolo` (2026-10), depois de 40+ specs não havia documento de jornadas: o agente só propôs escrevê-lo quando perguntado. A matéria-prima já existe — `critical_journeys` + `journeys` (jornadas e o teste que as prova) e os ADRs de stack por camada (greenfield) ou de as-is (brownfield) — mas nada a transforma em documento, e o G7 só pede "docs raiz" genéricos (`CLAUDE.md`, `README.md`).

**Objetivos (dentro do escopo):**
- Chave `living_docs` no sdd-config com o caminho de cada documento (`journeys`, `system_map`); `""` ou ausente = desligado.
- Comando `living-docs [--init]`: mostra a cobertura de cada documento; `--init` cria os que faltam a partir de templates, já preenchidos com as jornadas críticas (e as specs/E2E que as provam) e os ADRs aceitos.
- Templates `references/template-journeys.md` e `references/template-system-map.md`, agnósticos de stack.
- `validate`: avisos (WARN, nunca erro) para documento configurado e ausente, jornada crítica sem seção no guia, jornada desconhecida citada no guia e ADR aceito não citado no mapa.
- Caminhos de `living_docs` nunca contam como fora de escopo (como `root_docs`).
- Instruções: `SKILL.md` (CLOSE e tabela de comandos), `gates.md` (G7), `greenfield.md` (fundação), `brownfield.md` (baseline), `template-full.md` (item da Definição de Pronto), `sdd-config.template.yml`, `private-mode.md`, README e CHANGELOG.
- Modo privado: os documentos vivem no `spec_root`, nunca no repositório do time.

**Não-objetivos (fora do escopo):**
- Documento "por funcionalidade" da stack: duplicaria o "Como foi feito" das specs e desatualiza rápido (decisão da conversa de 2026-10-26).
- Gerar a prosa dos documentos: a ferramenta gera o esqueleto e checa a cobertura; o agente e o humano escrevem o conteúdo.
- Detectar se o conteúdo está **correto** ou se mudou no mesmo PR da spec: a checagem é de cobertura (IDs presentes), não de semântica.
- Mapa "funcionalidade → componentes" gerado a partir de `touches` (pode virar spec própria).
- Adotar os documentos no próprio `ai-dev-brain` (spec própria, se fizer sentido).
- Diagramas obrigatórios ou formato específico (C4, Mermaid etc.): o template sugere, não exige.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0003@1 — `project.private` e `project.spec_root` decidem onde os documentos ficam no modo privado.
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Referências: `validate_journeys` e `journey_coverage` (`spec_graph.py:1063`) para checagem de cobertura que vira WARN no `validate`; `cmd_journeys` (`:1096`) para um comando informativo; `Project.scope_exempt` (`:588`) para caminhos de documentação fora do escopo; `references/template-*.md` + `cmd_new` para gerar arquivo a partir de template; `cfg_map`/`cfg` para ler o sdd-config.

**Decisão:** função pura `living_docs_findings(journeys, guide_text, adrs, map_text)` devolve os achados; `validate_living_docs` os transforma em WARN; `cmd_living_docs` imprime a cobertura e, com `--init`, renderiza os templates sem sobrescrever arquivos existentes. A base dos caminhos é a raiz do repositório no modo completo e o `spec_root` no modo privado (API da SPEC-0003). Os templates ficam em `references/` (ADR-0001: `assets/` é só o que `vendor` instala).

**Justificativa:** segue a regra da skill de que o que importa é checado por ferramenta e não por texto (mandato 5), com o mesmo mecanismo das jornadas críticas; avisos em vez de erros porque documento de pessoas não deve bloquear entrega. Agnóstico de stack: os documentos são Markdown, as camadas são as mesmas que a skill já usa (UI, backend, dados, infra, entrega, observabilidade, testes) e nenhuma ferramenta nova é chamada (ADR-0001).

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** reaproveitar `root_docs` (é uma lista genérica, sem saber o que cada arquivo deve conter, por isso o guia nunca nascia); erro no `validate` (bloquearia entregas por documentação de pessoas); documento por funcionalidade (fora do escopo, ver acima); gerar o documento inteiro a cada `index` como o `INDEX.md` (sobrescreveria a prosa escrita por pessoas).

**ADRs:** ADR-0001 (fronteiras: script único, `references/` para detalhe, agnóstico), ADR-0002 (testes da CLI por integração), ADR-0006 (modo privado: nada do SDD no repositório do time).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a checagem lê dois arquivos e os ADRs já carregados; o `validate` de um projeto com 100 specs e 30 ADRs não fica mais de 10% mais lento (medido no IT-01).
- **Segurança:** `--init` nunca sobrescreve um arquivo existente e só escreve dentro da raiz do repositório ou do `spec_root`; caminho configurado fora deles é recusado.
- **Privacidade e dados pessoais:** no modo privado os documentos ficam no `spec_root`; nada é escrito no repositório do time (IT-03).
- **Disponibilidade e resiliência:** projeto sem `living_docs` no sdd-config se comporta exatamente como hoje (IT-04).
- **Acessibilidade (UI):** N/A — CLI e Markdown.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chave `living_docs` do sdd-config, comando `living-docs`, avisos do `validate`, templates e instruções.

```text
sdd-config.yml:
  living_docs:
    journeys: docs/jornadas.md        # guia de jornadas; "" = desligado
    system_map: docs/arquitetura.md   # mapa do sistema; "" = desligado
  - chave ausente = desligado (projetos existentes não mudam); sdd-config.template.yml traz os dois caminhos preenchidos
  - caminhos relativos à raiz do repositório; em modo privado, relativos ao spec_root
  - caminho absoluto ou com ".." que saia da base → erro de configuração no validate e no living-docs
  - os caminhos configurados entram em scope_exempt (nunca fora do escopo no G4)

spec_graph.py living-docs:
  para cada documento configurado imprime: caminho, "existe" | "ausente", e
    guia: "✅ <id>" para jornada crítica citada com [jornada: <id>]; "⚠ <id>" para a que falta; "✖ <id>" para id desconhecido
    mapa: "✅ ADR-NNNN" para ADR accepted citado pelo ID; "⚠ ADR-NNNN" para o que falta
  nenhum configurado → "Nenhum documento vivo em living_docs no sdd-config.yml."; exit 0 sempre

spec_graph.py living-docs --init:
  cria cada documento configurado e ausente a partir de references/template-journeys.md / template-system-map.md
    guia: uma seção por jornada crítica — "## <título> [jornada: <id>]" — com os campos Perfil, Passo a passo,
      Como reproduzir localmente, e "Provada por: <SPEC-NNNN> (<E2E-xx>)" quando journey_coverage tiver a prova
      ou "Provada por: — (sem E2E)" quando não tiver; sem jornadas críticas → uma seção de exemplo com instrução
    mapa: seções Visão geral, Componentes por camada (UI, backend, dados, infraestrutura, entrega, observabilidade,
      testes), Serviços externos, Ambientes, Rodar localmente, Caminho até produção, Decisões — esta com
      "- ADR-NNNN — <título>" para cada ADR accepted
  documento existente → "mantido: <caminho>", conteúdo intocado
  imprime "criado: <caminho>" para cada arquivo criado; exit 0
  em modo privado escreve no spec_root e registra o commit lá, como os demais comandos que escrevem registros

validate (WARN, nunca ERROR; nenhum aviso com living_docs desligado):
  "living_docs.<chave>: <caminho> não existe — rode living-docs --init"
  "guia de jornadas sem a jornada crítica <id> — adicione a seção com [jornada: <id>]"
  "guia de jornadas cita [jornada: <id>], que não está em critical_journeys"
  "mapa do sistema não cita <ADR-NNNN> (accepted) — diga onde a decisão aparece no sistema"
  ADRs proposed, deprecated ou superseded não geram aviso

Instruções:
  SKILL.md: linha de living-docs na tabela de comandos; CLOSE atualiza guia e mapa quando a entrega muda uma jornada
    ou um componente
  gates.md (G7): guia e mapa refletem a entrega; validate sem avisos de living_docs para as jornadas/ADRs da spec
  greenfield.md: a fundação cria os dois documentos (living-docs --init) junto com o walking skeleton
  brownfield.md: o baseline de adoção grava o mapeamento da arquitetura no mapa do sistema e cria o guia
  template-full.md: item "Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um
    componente (G7)" na Definição de Pronto
  private-mode.md: linha "Documentos vivos" na tabela "Where things live" (<spec_root>/<caminho>)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. Novos: `references/template-journeys.md`, `references/template-system-map.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Cobertura completa | toda jornada crítica com seção; todo ADR accepted citado | nenhum achado | UT-01 |
| Jornada faltando | jornada crítica sem `[jornada: <id>]` no guia | achado "falta" com o id | UT-01, IT-01 |
| Jornada desconhecida | guia cita id fora de `critical_journeys` | achado "desconhecida" | UT-01 |
| ADR não citado | ADR accepted sem o ID no mapa; superseded sem o ID | achado só para o accepted | UT-01, IT-01 |
| Desligado | `living_docs` ausente ou caminhos `""` | nenhuma checagem, nenhum aviso | UT-02, IT-04 |
| Caminho inválido | caminho absoluto ou saindo da base com `..` | erro de configuração | UT-02 |
| Documento ausente | caminho configurado sem arquivo | WARN no validate; exit do validate inalterado | IT-01 |
| Init cria | documentos ausentes, jornadas e ADRs no projeto | arquivos com seções por jornada (com prova) e lista de ADRs; validate sem avisos de living_docs | IT-02 |
| Init preserva | documento já existe | "mantido", conteúdo idêntico | IT-02 |
| Modo privado | `living-docs --init` com modo privado | arquivos no spec_root, nada no repositório, leak-check limpo | IT-03, CT-01 |
| Escopo | commit da spec altera `docs/jornadas.md` fora de `touches` | não aparece como fora do escopo no `verify` | IT-05 |
| Instruções do agente | SKILL.md, gates.md, greenfield.md, brownfield.md, template-full.md, sdd-config template, private-mode.md | cada um traz o trecho do contrato | UT-03 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — `validate` e `verify` já são fixados pela suíte atual (`test_spec_graph.py`); IT-04 é a guarda do comportamento com `living_docs` desligado.

### 7.2 Testes Unitários
- **UT-01** — Dado jornadas `{agenda, moderacao}`, um guia que cita `[jornada: agenda]` e `[jornada: velha]`, ADRs `ADR-0001` (accepted), `ADR-0002` (accepted) e `ADR-0003` (superseded) e um mapa que cita só `ADR-0001`, quando `living_docs_findings` roda, então devolve: jornada faltando `moderacao`, jornada desconhecida `velha`, ADR não citado `ADR-0002` — e nada para `ADR-0003`; com tudo citado, devolve lista vazia.
- **UT-02** — Dado sdd-configs sem `living_docs`, com caminhos `""`, com `docs/jornadas.md`, com `/etc/x.md` e com `../fora.md`, quando os caminhos são resolvidos, então os dois primeiros desligam a checagem, o terceiro resolve dentro da base e os dois últimos dão erro de configuração.
- **UT-03** — Dado os arquivos de instrução da skill, quando lidos, então `SKILL.md` cita `living-docs`; `gates.md` cita guia e mapa no G7; `greenfield.md` e `brownfield.md` citam `living-docs --init`; `template-full.md` tem o item da Definição de Pronto; `sdd-config.template.yml` tem `living_docs` com `journeys` e `system_map`; `private-mode.md` tem a linha "Documentos vivos".

### 7.3 Testes de Integração
- **IT-01** — Dado um repositório temporário com `living_docs` configurado, duas jornadas críticas, um guia sem uma delas, um mapa sem um ADR accepted e o arquivo do mapa ausente numa segunda rodada, quando roda `validate`, então a saída tem os WARN do contrato, o exit é o mesmo de antes (avisos não reprovam) e o tempo fica dentro do RNF de desempenho.
- **IT-02** — Dado um repositório temporário com duas jornadas críticas (uma provada por spec implementada com um E2E marcado `[jornada: agenda]`) e dois ADRs accepted, quando roda `living-docs --init`, então cria os dois documentos com "## … [jornada: agenda]", "Provada por: SPEC-0001 (<ID do E2E>)", "Provada por: — (sem E2E)" para a outra e "- ADR-0001 — …"; em seguida `validate` não tem aviso de living_docs; e uma segunda rodada imprime "mantido" com os arquivos byte a byte iguais.
- **IT-03** — Dado o modo privado (registro de teste, `spec_root` fora do repositório) com `living_docs` no sdd-config do `spec_root`, quando roda `living-docs --init`, então os arquivos são criados no `spec_root` (e commitados lá), o repositório do time continua sem eles e `leak-check` sobre o repositório não acha nada.
- **IT-04** — (guarda: passa antes da mudança) Dado um projeto sem `living_docs` no sdd-config, quando roda `validate`, então a saída não tem nenhum aviso de documentos vivos e o exit é o de hoje.
- **IT-05** — Dado uma spec com `touches: [src/**, tests/**]` e um commit dela que também altera `docs/jornadas.md` (configurado em `living_docs`), quando roda `verify SPEC-0001`, então `docs/jornadas.md` não aparece como fora do escopo.

### 7.4 Testes de Contrato
- **CT-01** — Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando `living-docs` e `validate` resolvem os caminhos, então usam `project.spec_root` como base (e não a raiz do repositório) — verificado com um registro de teste e um `spec_root` fora do repositório.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração (IT-01 a IT-05 rodam o comando real em repositórios temporários).

### 7.6 Outros
- Tempo do `validate` lido no IT-01 (RNF de desempenho).

**Dublês e dados de teste:** repositórios temporários com specs e ADRs mínimos; registro do usuário isolado (`SDD_CONFIG_HOME`), como na SPEC-0010.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; projetos existentes só são afetados se adicionarem `living_docs` ao sdd-config.
- **Dados/schema:** chave nova e opcional `living_docs` no sdd-config.
- **Compatibilidade:** sem `living_docs` nada muda (IT-04); `upgrade` não mexe no sdd-config.
- **Observabilidade:** avisos do `validate` e saída do `living-docs`.
- **Rollback:** `git revert` do merge; `SDD_TOOL_VERSION` e CHANGELOG conforme o ADR-0005.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Quais documentos? — Só dois: guia de jornadas e mapa do sistema; documento por funcionalidade fica fora (thomas concordou com a recomendação, 2026-10-26)
- [x] Aviso ou erro no validate? — Aviso: documentação de pessoas não bloqueia entrega (thomas concordou com a recomendação, 2026-10-26)
- [x] Projetos existentes passam a receber avisos? — Não: chave ausente = desligado; só o template novo traz os caminhos, e o baseline do brownfield propõe ativar (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)
- [x] Onde ficam no modo privado? — No `spec_root`, pois citam IDs de jornada e de ADR do SDD (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Checagem e configuração**
- [ ] Red: UT-01, UT-02, IT-01, IT-04 (guarda), IT-05 e CT-01 com a tag `SPEC-0011:<ID>`, falhando pelo motivo certo (IT-04 passando)
- [ ] Green: `living_docs_paths`, `living_docs_findings`, `validate_living_docs` e `scope_exempt`, seguindo `validate_journeys`
- [ ] Refactor mantendo tudo verde

**Fase 2: Comando e templates**
- [ ] Red: IT-02 e IT-03 falhando pelo motivo certo
- [ ] Green: `cmd_living_docs` (`--init`), `references/template-journeys.md` e `references/template-system-map.md`
- [ ] Refactor mantendo tudo verde

**Fase 3: Instruções**
- [ ] Red: UT-03 falhando pelo motivo certo
- [ ] Green: SKILL.md, gates.md, greenfield.md, brownfield.md, template-full.md, sdd-config.template.yml, private-mode.md e README
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `SDD_TOOL_VERSION` e CHANGELOG (ADR-0005)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — ffed129 | 2026-10-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=12, skipped=1)) — 0c1a819 | 2026-10-26 |
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
| IMP-01 | 2026-10-26 | G1 | spec | O IT-02 do plano cita o ID de exemplo E2E-01 (dado de teste da fixture), que o verify lê como teste do plano desta spec e cobra a tag SPEC-0011:E2E-01; o IT-05 pede touches [src/**], mas o commit red em tests/ ficaria fora do escopo na fixture | gate G1 --run (FAIL em 0c1a819) | thomas | Emenda v1 — IT-02 sem ID literal de E2E e IT-05 com touches [src/**, tests/**] na fixture; contrato inalterado (aprovada por thomas em 2026-10-26) | 2026-10-26 |

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0011`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 1 (emenda v1, contrato inalterado) | 2026-10-26 | IT-02 descreve o E2E da fixture sem ID literal; IT-05 usa `touches: [src/**, tests/**]` na fixture | o `verify` lia o `E2E-01` de exemplo como teste desta spec; sem `tests/**` o commit red da fixture caía fora do escopo (IMP-01) | Nenhuma | thomas, 2026-10-26 |
