---
id: SPEC-0017
title: "second-brain: esqueleto, configuração em duas camadas, onboarding e doctor"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: []
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/SKILL.md, skills/second-brain/scripts/brain.py, skills/second-brain/references/config.md, skills/second-brain/references/providers.md, skills/second-brain/references/vault-layout.md, skills/second-brain/assets/**, skills/second-brain/tests/**, skills/second-brain/CHANGELOG.md, .github/workflows/ci.yml, README.md, CHANGELOG.md]
adrs: [ADR-0007, ADR-0008, ADR-0002, ADR-0003, ADR-0005]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0017 — second-brain: esqueleto, configuração em duas camadas, onboarding e doctor

## 1. Visão Geral
Cria a skill `second-brain` com a base que as outras filhas da SPEC-0016 usam. São quatro peças:
- A estrutura do vault, em inglês.
- A configuração em duas camadas: compartilhada no vault e local por máquina.
- O onboarding (`init`), que cria um vault novo ou adota um existente.
- O `doctor`, que mostra o que está configurado, o que funciona e o que falta.

O `SKILL.md` diz ao agente: sem configuração, conduzir o onboarding; com configuração, usar direto. A CI passa a rodar a suíte da skill nova.

## 2. Motivação & Escopo
**Motivação:** a skill é agnóstica (SPEC-0016). Qualquer pessoa precisa conseguir configurar na primeira vez, e quem já configurou usa sem responder nada de novo, em qualquer máquina. Todas as outras filhas dependem de saber onde o vault está e como ele é organizado.

**Objetivos (dentro do escopo):**
- `skills/second-brain/` com `SKILL.md`, `scripts/brain.py`, `references/` (config, provedores, estrutura do vault), `assets/` (modelos de nota e `brain-config.yml` padrão), `tests/` e `CHANGELOG.md`.
- Estrutura padrão do vault: `inbox/`, `raw/`, `projects/`, `areas/`, `resources/`, `archive/`, `mocs/`, `templates/`, `index.md`, `log.md`, `brain-config.yml`.
- `brain.py init` não interativo, guiado por flags. A conversa com o usuário fica com o agente, que segue o `SKILL.md`. Cria um vault novo ou adota um existente sem mover nem alterar arquivos.
- `brain.py init --join`: numa máquina nova, grava só a configuração local apontando para um vault que já tem `brain-config.yml`.
- `brain.py config` (mostra a configuração efetiva e de onde veio cada valor) e `brain.py context add <nome> --folder <pasta> --title <título>`.
- `brain.py doctor`: configuração local, vault, pasta de arquivos, `brain-config.yml`, contextos e processadores.
- Teste de arquitetura do ADR-0007, CI rodando a suíte nova e README listando a skill.

**Não-objetivos (fora do escopo):**
- Criar ou buscar notas (SPEC-0018, SPEC-0019), rodar processadores (SPEC-0022) e `lint` (SPEC-0023). O `doctor` só confere se os executáveis dos processadores existem.
- Instalar ou configurar o app de sincronização do provedor. O guia `providers.md` explica, e a skill não faz.
- Reorganizar um vault adotado.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A (só Python 3.9+).

## 4. Decisão Arquitetural
**Contexto:** projeto existente. A referência é a `sdd-management`:
- arquivo único com `argparse` e um `cmd_<comando>` por subcomando (`skills/sdd-management/scripts/spec_graph.py`);
- configuração do usuário isolada por variável de ambiente (`SDD_CONFIG_HOME` em `spec_graph.py:480`, que vira `BRAIN_CONFIG_HOME`);
- leitura de YAML com um subconjunto próprio (`parse_yaml_subset`);
- testes de integração pela CLI em diretório temporário (`Project` em `skills/sdd-management/tests/test_spec_graph.py`);
- checadores de arquitetura (`skills/sdd-management/tests/architecture_rules.py`).

**Decisão:** `brain.py` com `load_config()`, que junta a configuração local (`$BRAIN_CONFIG_HOME/config.yml`, padrão `~/.config/second-brain/config.yml`) e a compartilhada (`<vault>/brain-config.yml`) e devolve a efetiva com a origem de cada valor. `init` copia `assets/brain-config.yml` e os modelos de `assets/templates/` para o vault, cria as pastas que faltam e grava a configuração local. Com `--adopt`, não cria pastas que o usuário não tem e registra no `layout` as pastas que ele já usa (flags `--map inbox=Inbox` etc.).

**Justificativa:** segue o ADR-0007 (arquivo único, só biblioteca padrão) e o ADR-0008 (a skill só recebe caminhos; configuração em duas camadas). `init` não interativo é testável e funciona com qualquer agente.

**Desvio do padrão existente:** Nenhum. O parser de YAML é próprio do `brain.py` (ADR-0007), escrito no mesmo estilo do `parse_yaml_subset`.

**Alternativas descartadas:**
- `init` interativo com `input()`: agentes rodam comandos sem terminal interativo, e seria difícil de testar.
- Configuração só no vault: o caminho do vault muda por máquina.
- JSON no lugar de YAML: o Obsidian e o frontmatter já usam YAML, e o usuário edita esse arquivo à mão.

**ADRs:** ADR-0007 e ADR-0008 (criados pela SPEC-0016 e aplicados aqui); ADR-0002, ADR-0003 e ADR-0005 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `doctor` e `config` em menos de 1 s num vault com 5.000 notas (medido na revisão com um vault gerado).
- **Segurança:** o `init` nunca sobrescreve arquivo existente. Sem `--force`, falha se já houver `brain-config.yml` com conteúdo diferente; com `--force`, sobrescreve só o `brain-config.yml` e guarda o anterior em `brain-config.yml.bak`. Nenhum processo externo é executado (o `doctor` só usa `shutil.which`).
- **Privacidade e dados pessoais:** a configuração local fica fora do repositório e do vault. O `brain-config.yml` nunca tem caminho absoluto (UT-03). Testes isolam `HOME` e `BRAIN_CONFIG_HOME` (ADR-0002).
- **Disponibilidade e resiliência:** vault em pasta da nuvem ainda não sincronizada (pasta inexistente) → o `doctor` diz qual caminho falta e sai com 1, sem traceback.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** estrutura do vault, `brain-config.yml`, configuração local, comandos `init`, `config`, `context add`, `doctor`, e as instruções do `SKILL.md` para o onboarding.

```text
Configuração local — $BRAIN_CONFIG_HOME/config.yml (padrão ~/.config/second-brain/config.yml):
  vault: <caminho absoluto do vault>
  files: <caminho absoluto da pasta de arquivos pesados, fora do vault>
  provider: google-drive | onedrive | icloud | local

Configuração compartilhada — <vault>/brain-config.yml (nunca com caminho absoluto):
  version: 1
  language: auto                    # idioma do conteúdo; estrutura sempre em inglês
  layout:                           # pastas relativas ao vault
    inbox: inbox
    raw: raw
    mocs: mocs
    templates: templates
    index: index.md
    log: log.md
  para: {projects: projects, areas: areas, resources: resources, archive: archive}
  contexts:                         # nome → pasta (relativa ao vault) + título do MOC
    college: {folder: projects/college, title: College}
  processors: {}                    # ADR-0009 / SPEC-0022

Estrutura criada por init (vault novo):
  inbox/ raw/ projects/ areas/ resources/ archive/ mocs/ templates/<tipo>.md index.md log.md brain-config.yml
  index.md e log.md com regiões geradas <!-- brain:begin ... --> / <!-- brain:end ... -->

brain.py init --vault P --files F --provider X [--adopt [--map chave=pasta ...]] [--context nome=pasta[:título] ...] [--force]
  vault novo: cria a estrutura, copia os modelos, grava as duas configurações; imprime "Vault criado em P" e a lista do que foi criado
  --adopt: não cria pastas de PARA que não existem; mapeia layout pelos --map; cria só inbox/, raw/, templates/,
           index.md, log.md e brain-config.yml se faltarem; nenhum arquivo existente é movido ou alterado
  brain-config.yml existente e igual: só grava a configuração local ("Vault já configurado")
  brain-config.yml existente e diferente sem --force: exit 2, "brain-config.yml já existe — use --join ou --force"
  vault ou files inexistentes: cria files; vault inexistente com --adopt → exit 2 "vault não encontrado: P"
  files dentro do vault: exit 2 "files precisa ficar fora do vault"
  provider fora da lista: exit 2 com a lista
  toda escrita no vault: linha em log.md "AAAA-MM-DD HH:MM init <resumo>"

brain.py init --join --vault P --files F --provider X
  exige <vault>/brain-config.yml; grava só a configuração local; exit 2 "vault sem brain-config.yml — rode init" se faltar

brain.py config [--json]
  configuração efetiva, cada valor com a origem (local | vault | padrão)
  sem configuração local: exit 3, "second-brain não configurado nesta máquina — rode init (ou init --join)"

brain.py context add NOME --folder PASTA [--title T]
  acrescenta em contexts no brain-config.yml, cria PASTA e mocs/NOME.md se faltarem; contexto existente: exit 2

brain.py doctor [--json]
  uma linha por item: "OK|AVISO|ERRO <item> — <detalhe>"
  itens: configuração local, vault, files, brain-config.yml (versão e chaves), pastas do layout, contextos,
         processadores (executável no PATH), provider (aviso sobre celular do providers.md)
  exit 0 sem ERRO; 1 com ERRO; 3 sem configuração local (mesma mensagem do config)

BRAIN_CONFIG_HOME (variável de ambiente) troca a pasta da configuração local; usada nos testes.

SKILL.md (instruções para o agente):
  antes de qualquer fluxo, rodar `brain.py config`; exit 3 → onboarding:
    perguntar provedor, se já existe vault (novo ou adotar), onde ficam vault e arquivos, contextos iniciais,
    processadores desejados; avisar sobre o celular conforme references/providers.md; rodar init com as flags;
    rodar doctor e mostrar o resultado
  vault com brain-config.yml e máquina sem configuração local → perguntar só os caminhos e rodar init --join
  configurado → seguir direto o fluxo pedido, sem perguntar nada de configuração
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. A CI (`.github/workflows/ci.yml`) ganha o passo `python -m unittest discover -s skills/second-brain/tests -v`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Vault novo | `init` com vault vazio | estrutura completa, duas configurações, log com `init` | IT-01 |
| Adotar vault | `init --adopt --map inbox=Inbox` num vault com notas | nenhum arquivo existente muda; layout aponta `Inbox`; cria só o que falta | IT-02 |
| Já configurado igual | `init` de novo com o mesmo vault | só a configuração local; "Vault já configurado" | IT-03 |
| Config diferente | `brain-config.yml` diferente sem `--force` | exit 2 com a mensagem | IT-03 |
| Force | `--force` | `.bak` com o anterior; novo `brain-config.yml` | IT-03 |
| Máquina nova | `init --join` com outro caminho | só a configuração local; `config` mostra os mesmos contextos | IT-04 |
| Join sem config | `init --join` em vault sem `brain-config.yml` | exit 2 com a mensagem | IT-04 |
| files dentro do vault | `--files <vault>/files` | exit 2 | UT-02 |
| Provider inválido | `--provider dropbox` | exit 2 com a lista | UT-02 |
| Não configurado | `config` ou `doctor` sem configuração local | exit 3 com a mensagem | IT-05 |
| Origem dos valores | `config --json` | cada valor com local, vault ou padrão | UT-01 |
| Sem caminho absoluto | `brain-config.yml` gerado | nenhum valor é caminho absoluto | UT-03 |
| Doctor saudável | vault ok, processador inexistente | OK nos itens; AVISO no processador; exit 0 | IT-06 |
| Doctor com erro | vault removido | ERRO no vault; exit 1; sem traceback | IT-06 |
| Contexto novo | `context add college --folder projects/college` | entra no `brain-config.yml`, pasta e MOC criados | IT-07 |
| Contexto repetido | mesmo nome | exit 2 | IT-07 |
| Parser YAML | mapas aninhados, listas inline, comentários, strings com `:` | lido igual ao esperado | UT-04 |
| Instruções | `SKILL.md`, `references/` | onboarding, `--join` e "configurado → direto" descritos | UT-05 |
| Arquitetura | código de `skills/second-brain/` | regras do ADR-0007 | UT-06 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — skill nova, sem código existente.

### 7.2 Testes Unitários
- **UT-01** — Dado uma configuração local com `vault` e um `brain-config.yml` com `contexts`, quando `load_config` roda, então devolve a configuração efetiva com `vault` de origem `local`, `contexts` de origem `vault` e `layout.inbox` de origem `padrão` quando ausente.
- **UT-02** — Dado argumentos de `init` com `files` dentro do vault, ou com `provider` fora de `google-drive | onedrive | icloud | local`, quando validados, então a validação devolve o erro com a mensagem do contrato.
- **UT-03** — Dado o `brain-config.yml` gerado por `init` para vaults em `/Users/x/...` e `C:\Users\x\...`, quando lido, então nenhum valor é caminho absoluto.
- **UT-04** — Dado textos YAML com mapas aninhados, listas inline e em bloco, comentários, strings com `:` e aspas, quando o parser do `brain.py` lê e o escritor regrava, então os valores lidos são os esperados e a ida e volta preserva os dados.
- **UT-05** — Dado `SKILL.md`, `references/config.md` e `references/providers.md`, quando lidos, então o `SKILL.md` manda rodar `brain.py config` antes de qualquer fluxo, descreve o onboarding (exit 3), o `init --join` e o uso direto quando configurado; `providers.md` tem uma seção por provedor da v1 com o aviso sobre iOS e Android.
- **UT-06** — Dado o código de `skills/second-brain/scripts/brain.py`, quando os checadores de arquitetura rodam, então não há import fora da biblioteca padrão, nem import de `skills/sdd-management` ou `tools`, nem chamada de processo fora da função de processadores, nem caminho pessoal absoluto em `skills/second-brain/` (fora de `tests/`).

### 7.3 Testes de Integração
- **IT-01** — Dado um diretório temporário vazio e `BRAIN_CONFIG_HOME` isolado, quando roda `brain.py init --vault V --files F --provider google-drive --context college=projects/college:College`, então V tem toda a estrutura do contrato, `brain-config.yml` tem o contexto, a configuração local tem os caminhos, `log.md` tem a linha de `init` e o exit é 0.
- **IT-02** — Dado um vault com `Inbox/a.md`, `Notas/b.md` e `.obsidian/`, quando roda `init --adopt --map inbox=Inbox`, então o conteúdo e a data de modificação de `a.md`, `b.md` e `.obsidian/` não mudam, nenhuma pasta de PARA é criada, `layout.inbox` é `Inbox` e são criados só `raw/`, `templates/`, `index.md`, `log.md` e `brain-config.yml`.
- **IT-03** — Dado um vault já criado, quando roda `init` de novo igual, então imprime "Vault já configurado"; com `brain-config.yml` alterado à mão e sem `--force`, sai com 2; com `--force`, cria `brain-config.yml.bak` com o conteúdo anterior.
- **IT-04** — Dado o vault do IT-01 e uma segunda `BRAIN_CONFIG_HOME` com outro caminho para o mesmo vault (link simbólico), quando roda `init --join`, então só a configuração local é gravada e `config --json` mostra os mesmos contextos nas duas; num vault sem `brain-config.yml`, `--join` sai com 2.
- **IT-05** — Dado `BRAIN_CONFIG_HOME` vazio, quando roda `config` e `doctor`, então os dois saem com 3 e a mensagem "second-brain não configurado nesta máquina — rode init (ou init --join)".
- **IT-06** — Dado o vault do IT-01 com um processador `pdf` cujo executável não existe, quando roda `doctor`, então os itens de configuração são OK, o processador é AVISO e o exit é 0; depois de remover a pasta do vault, `doctor` mostra ERRO no vault, sai com 1 e não imprime traceback.
- **IT-07** — Dado o vault do IT-01, quando roda `context add work --folder areas/work --title Work`, então o contexto entra no `brain-config.yml`, `areas/work/` e `mocs/work.md` existem e `log.md` registra; repetir o comando sai com 2.

### 7.4 Testes de Contrato
- N/A — esta spec não consome contrato de outra. As filhas seguintes dependem da implementação (`depends_on`), e o contrato delas é coberto pelos próprios testes.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a skill não tem interface própria. A jornada do usuário passa pela CLI e é coberta pelos testes de integração (IT-01 a IT-07). A conversa do agente segue o `SKILL.md`, verificado no UT-05.

### 7.6 Outros
- Tempo do `doctor` num vault gerado com 5.000 notas (RNF de desempenho), medido na revisão.

**Dublês e dados de teste:** diretórios temporários para vault, arquivos e `BRAIN_CONFIG_HOME`; `HOME` isolado; vaults de exemplo gerados pelos próprios testes.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15, Ubuntu), como no ADR-0002.

## 8. Plano de Rollout
- **Estratégia:** deploy direto. A skill é nova e é instalada copiando `skills/second-brain/` para o diretório de skills da ferramenta (README).
- **Dados/schema:** `brain-config.yml` nasce com `version: 1`. Mudanças futuras de schema sobem a versão, e o `doctor` aponta vault com versão antiga.
- **Compatibilidade:** N/A — primeira versão.
- **Observabilidade:** `log.md` do vault registra toda escrita do `brain.py`; `doctor` mostra o estado.
- **Rollback:** `git revert` do merge; quem instalou volta a pasta anterior. O vault não é alterado pelo rollback.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Arquitetura e parser**
- [ ] Red: UT-06, UT-04 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [ ] Green: `tests/test_architecture.py` com as regras do ADR-0007; `brain.py` com `argparse` e parser/escritor de YAML
- [ ] Refactor mantendo tudo verde

**Fase 2: Configuração em duas camadas**
- [ ] Red: UT-01, UT-02, UT-03, IT-05 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [ ] Green: `load_config` com origem dos valores; validação de `init`; `config`
- [ ] Refactor mantendo tudo verde

**Fase 3: Onboarding e doctor**
- [ ] Red: IT-01, IT-02, IT-03, IT-04, IT-06, IT-07 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [ ] Green: `init` (novo, `--adopt`, `--force`, `--join`), `context add`, `doctor`, modelos em `assets/`
- [ ] Refactor mantendo tudo verde

**Fase 4: Instruções, CI e docs**
- [ ] Red: UT-05 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [ ] Green: `SKILL.md`, `references/config.md`, `providers.md`, `vault-layout.md`; passo da suíte nova em `.github/workflows/ci.yml`; README e CHANGELOG raiz
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [ ] Architect: `test` e `arch_test` do `docs/specs/sdd-config.yml` passam a incluir `skills/second-brain/tests`

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=25)) — 08d9ab7 | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0017`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
