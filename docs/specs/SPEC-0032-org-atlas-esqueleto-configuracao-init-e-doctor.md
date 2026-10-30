---
id: SPEC-0032
title: "org-atlas: esqueleto, configuração em duas camadas, init e doctor"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: []
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/config.md, skills/org-atlas/references/atlas-layout.md, skills/org-atlas/assets/atlas-config.yml, skills/org-atlas/assets/pages/**, skills/org-atlas/tests/helpers.py, skills/org-atlas/tests/architecture_rules.py, skills/org-atlas/tests/test_architecture.py, skills/org-atlas/tests/test_config.py, skills/org-atlas/CHANGELOG.md, .github/workflows/ci.yml, README.md]
adrs: [ADR-0010, ADR-0002, ADR-0003, ADR-0005]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0032 — org-atlas: esqueleto, configuração em duas camadas, init e doctor

## 1. Visão Geral
Cria a skill `org-atlas` com a base que as outras filhas da SPEC-0029 usam:
- A estrutura do atlas, em inglês.
- A configuração em duas camadas: compartilhada no atlas e local por máquina, onde as credenciais aparecem **só pelo nome**.
- O `init`, que cria um atlas novo no modo repositório ou local, e o `init --join` para uma máquina nova.
- O `config` e o `doctor`, que mostram o que está configurado, o que funciona e o que falta, sem nunca imprimir o valor de uma credencial.

O `SKILL.md` diz ao agente: sem configuração, conduzir o onboarding; com configuração, usar direto. A CI passa a rodar a suíte da skill.

## 2. Motivação & Escopo
**Motivação:** a skill é agnóstica de organização (SPEC-0029). Qualquer pessoa precisa conseguir configurar na primeira vez, e todas as outras filhas dependem de saber onde o atlas está, em que modo roda e quais credenciais a máquina declara.

**Objetivos (dentro do escopo):**
- `skills/org-atlas/` com `SKILL.md`, `scripts/atlas.py`, `references/` (configuração, estrutura do atlas), `assets/` (`atlas-config.yml` padrão e esqueletos de página), `tests/` e `CHANGELOG.md`.
- Estrutura do atlas: `ATLAS.md`, `atlas-config.yml`, `services/`, `platform/`, `conventions/`, `process/`, `glossary.md`, `snapshots/`.
- `atlas.py init`, `init --join`, `config` e `doctor`, não interativos (a conversa fica com o agente, que segue o `SKILL.md`).
- Teste de arquitetura do ADR-0010, CI rodando a suíte nova e README listando a skill.

**Não-objetivos (fora do escopo):**
- Rodar coletores e gravar snapshots (SPEC-0033), páginas de serviço e grafo (SPEC-0036), `curate`, `context`, `lint` e `vendor` (SPEC-0037 a SPEC-0040). O `doctor` só confere se o executável de cada coletor declarado existe.
- Rodar `git init` no modo local: o `atlas.py` não executa nada além dos coletores (ADR-0010); o `SKILL.md` orienta o agente a rodar, e o `doctor` avisa se a pasta não é um repositório git.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A (só Python 3.9+).

## 4. Decisão Arquitetural
**Contexto:** projeto existente. A referência é a `second-brain` (SPEC-0017): `skills/second-brain/scripts/brain.py` (arquivo único com `argparse` e um `cmd_<comando>` por subcomando, `load_config()` juntando a camada local e a compartilhada com a origem de cada valor, parser de YAML próprio, `BRAIN_CONFIG_HOME`), `skills/second-brain/tests/` (integração pela CLI em diretório temporário com `HOME` isolado) e `skills/second-brain/tests/architecture_rules.py`.

**Decisão:** `atlas.py` com o mesmo desenho: `load_config()` junta `$ATLAS_CONFIG_HOME/config.yml` (padrão `~/.config/org-atlas/config.yml`) e `<atlas>/atlas-config.yml`; `init` copia `assets/atlas-config.yml` e os esqueletos de `assets/pages/`. As credenciais da camada local são uma lista de **nomes** de variável de ambiente e de profile por coletor; o `atlas.py` valida o formato do nome e só verifica se a variável existe, sem ler o valor.

**Justificativa:** segue o ADR-0010 (arquivo único, só biblioteca padrão, credenciais fora do atlas) e repete um desenho que já funciona na `second-brain`.

**Desvio do padrão existente:** Nenhum. O parser de YAML é próprio do `atlas.py` (ADR-0010), no estilo do `brain.py`.

**Alternativas descartadas:** guardar credenciais na configuração local (cria um arquivo com segredos fora de um cofre); `init` interativo com `input()` (agentes rodam sem terminal interativo e seria difícil de testar).

**ADRs:** ADR-0010 (criado pela SPEC-0029 e aplicado aqui); ADR-0002, ADR-0003 e ADR-0005 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `config` e `doctor` em menos de 1 s num atlas com 500 serviços (atlas gerado na revisão).
- **Segurança:** o `init` nunca sobrescreve arquivo existente sem `--force`; nenhum processo externo é executado (o `doctor` usa só `shutil.which` e `os.environ`); nenhum valor de variável de ambiente é impresso (IT-05).
- **Privacidade e dados pessoais:** a configuração local fica fora do atlas e do repositório; o `atlas-config.yml` nunca tem caminho absoluto (UT-03); testes isolam `HOME` e `ATLAS_CONFIG_HOME`.
- **Disponibilidade e resiliência:** pasta do atlas inexistente → o `doctor` diz qual caminho falta e sai com 1, sem traceback.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** estrutura do atlas, `atlas-config.yml`, configuração local e os comandos `init`, `config` e `doctor`.

```text
Configuração local — $ATLAS_CONFIG_HOME/config.yml (padrão ~/.config/org-atlas/config.yml):
  atlas: <caminho absoluto do atlas nesta máquina>
  credentials:                       # só NOMES; nunca valores
    <id do coletor>: {env: [NOME_DA_VARIAVEL, ...], profile: <nome do profile>}
  nome de variável fora de ^[A-Z_][A-Z0-9_]*$ → exit 2 "credentials aceita só nomes de variável: <coletor>"

Configuração compartilhada — <atlas>/atlas-config.yml (nunca com caminho absoluto):
  version: 1
  organization: <nome>
  mode: repo | local
  language: auto                     # idioma do conteúdo; a estrutura é sempre em inglês
  stale_days: 14
  categories: [code, delivery]       # ADR-0011
  collectors: []                     # SPEC-0033
  redaction: {extra_patterns: []}    # SPEC-0033

Estrutura criada por init:
  ATLAS.md  atlas-config.yml  glossary.md  services/  platform/  conventions/  process/  snapshots/
  ATLAS.md e glossary.md com regiões geradas <!-- atlas:begin <nome> --> / <!-- atlas:end <nome> -->

atlas.py init --atlas P --org NOME --mode repo|local [--force]
  pasta vazia ou inexistente: cria a estrutura e as duas configurações; imprime "Atlas criado em P" e o que foi criado
  atlas-config.yml existente e igual: só grava a configuração local ("Atlas já configurado")
  atlas-config.yml existente e diferente, sem --force: exit 2 "atlas-config.yml já existe — use --join ou --force"
  pasta com conteúdo e sem atlas-config.yml: exit 2 "pasta não está vazia — escolha outra pasta"
  --force: sobrescreve só o atlas-config.yml e guarda o anterior em atlas-config.yml.bak
  mode fora de repo|local: exit 2 com as opções

atlas.py init --join --atlas P
  exige <P>/atlas-config.yml; grava só a configuração local; sem ele: exit 2 "atlas sem atlas-config.yml — rode init"

atlas.py config [--json]
  configuração efetiva, cada valor com a origem (local | atlas | padrão); credenciais mostradas só pelo nome
  sem configuração local: exit 3 "org-atlas não configurado nesta máquina — rode init (ou init --join)"

atlas.py doctor [--json]
  uma linha por item: "OK|AVISO|ERRO <item> — <detalhe>"
  itens: configuração local; pasta do atlas; atlas-config.yml (versão, chaves, sem caminho absoluto); estrutura;
         git (AVISO se a pasta não é repositório git); cada coletor (executável encontrado ou não);
         cada credencial ("definida" | "não definida", nunca o valor)
  exit 0 sem ERRO, 1 com ERRO, 3 sem configuração
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. O `SKILL.md` tem a seção "Antes de qualquer fluxo" (rodar `config`; exit 3 → onboarding) e o onboarding (organização, modo, onde fica o atlas, `git init` no modo local, credenciais por nome).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Atlas novo | pasta vazia, `--mode repo` | estrutura e configurações criadas, sem caminho absoluto no `atlas-config.yml` | UT-03, IT-01 |
| Atlas já configurado | mesmo `atlas-config.yml` | só a configuração local; nada sobrescrito | IT-02 |
| Configuração diferente | `atlas-config.yml` diferente, sem `--force` | exit 2 com a mensagem do contrato | IT-02 |
| Pasta ocupada | pasta com arquivos e sem `atlas-config.yml` | exit 2 | IT-02 |
| Máquina nova | `init --join` | só a configuração local | IT-03 |
| Sem configuração | `config` sem configuração local | exit 3 | IT-04 |
| Configuração efetiva | duas camadas presentes | valores com a origem de cada um | UT-01, IT-04 |
| Credencial com valor | `credentials.github.env: ["ghp_abc"]` | exit 2; valor não é gravado | UT-02 |
| Diagnóstico | atlas sem git, coletor ausente, variável definida e não definida | AVISO/ERRO por item, valor da variável nunca impresso | IT-05 |
| YAML da configuração | subconjunto usado nos arquivos | lido e escrito sem perder comentários do modelo | UT-04 |
| Fronteiras | código da skill | só biblioteca padrão, arquivo único, sem import entre skills, processo externo só na função de coletores, sem caminho pessoal | UT-05 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — skill nova.

### 7.2 Testes Unitários
- **UT-01** — Dado uma configuração local e um `atlas-config.yml`, quando `load_config()` roda, então devolve os valores efetivos com a origem `local`, `atlas` ou `padrão`.
- **UT-02** — Dado `credentials` com um valor que não é nome de variável, quando a configuração local é validada, então falha com "credentials aceita só nomes de variável" e nada é gravado.
- **UT-03** — Dado o `atlas-config.yml` gerado pelo `init`, quando é lido, então nenhum valor é caminho absoluto.
- **UT-04** — Dado os arquivos YAML do modelo, quando são lidos e reescritos pelo parser próprio, então os valores e os comentários do modelo são preservados.
- **UT-05** — Dado o código de `skills/org-atlas/`, quando os checadores de arquitetura rodam, então só há imports da biblioteca padrão, `atlas.py` é arquivo único, nenhum import entre skills, `subprocess` só na função que executa coletores e nenhum caminho pessoal fora dos testes (ADR-0010).

### 7.3 Testes de Integração
- **IT-01** — `init --mode repo` numa pasta vazia, pela CLI, com `HOME` isolado, cria a estrutura e as duas configurações.
- **IT-02** — `init` repetido com o mesmo conteúdo é idempotente; com conteúdo diferente sem `--force` sai com 2; com `--force` guarda o `.bak`; em pasta ocupada sai com 2.
- **IT-03** — `init --join` grava só a configuração local; sem `atlas-config.yml` sai com 2.
- **IT-04** — `config` sem configuração local sai com 3; com configuração, `--json` mostra a origem de cada valor.
- **IT-05** — `doctor` num atlas sem git, com um coletor cujo executável não existe e uma variável declarada definida com um valor conhecido: reporta AVISO e ERRO certos, sai com 1, e o valor da variável não aparece na saída.

### 7.4 Testes de Contrato
- N/A — o contrato desta spec (configuração e estrutura) é consumido pelas filhas por `depends_on`, já implementado.

### 7.5 Testes E2E
- N/A — ferramenta de linha de comando usada pelo agente; a jornada de ponta a ponta (scan → context) é provada pela SPEC-0038.

### 7.6 Outros
- Lint com Ruff (ADR-0003) e a suíte em Python 3.9 e 3.15 na CI.

**Dublês e dados de teste:** diretórios temporários com `HOME` e `ATLAS_CONFIG_HOME` isolados; coletor declarado com executável inexistente.

**Ambiente de execução:** local e CI (`unittest`), sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto — pasta nova da skill, instalada por cópia.
- **Dados/schema:** N/A — `version: 1` no `atlas-config.yml` permite migrar depois.
- **Compatibilidade:** N/A — skill nova.
- **Observabilidade:** saída do `doctor`.
- **Rollback:** reverter o PR; nenhum dado de usuário é afetado.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Idioma da estrutura do atlas — inglês; conteúdo no idioma da organização (thomas, 2026-10-30)
- [x] Valor padrão de `stale_days` — 14 (thomas, 2026-10-30)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0032`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
