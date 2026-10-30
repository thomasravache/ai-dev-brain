---
id: SPEC-0017
title: "second-brain: esqueleto, configuração em duas camadas, onboarding e doctor"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0016
depends_on: []
consumes_contract: []
contract_version: 2
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
  pasta do vault com conteúdo e sem brain-config.yml, sem --adopt: exit 2 "vault não está vazio — use --adopt" (v2)
  --adopt com log.md ou index.md do usuário (sem marcadores brain:begin): exit 2
    "<arquivo> já existe — use --map log=<outro> (ou --map index=<outro>)"; nada é escrito (v2)
  brain-config.yml gerado a partir de assets/brain-config.yml, mantendo os comentários; só os valores de --map e
    --context mudam (v2)
  toda escrita no vault: linha no fim de log.md "- AAAA-MM-DD HH:MM init <resumo>" (formato da SPEC-0019; v2)

brain.py init --join --vault P --files F --provider X
  exige <vault>/brain-config.yml; grava só a configuração local; exit 2 "vault sem brain-config.yml — rode init" se faltar

brain.py config [--json]
  configuração efetiva, cada valor com a origem (local | vault | padrão)
  sem configuração local: exit 3, "second-brain não configurado nesta máquina — rode init (ou init --join)"

brain.py context add NOME --folder PASTA [--title T]
  acrescenta em contexts no brain-config.yml, cria PASTA e mocs/NOME.md se faltarem; contexto existente: exit 2
  só insere linhas em contexts, com a indentação das entradas existentes; nunca reescreve o resto do arquivo (v2)
  contexts escrito em forma inline com itens: exit 2 "contexts está em forma inline — converta para bloco" (v2)

brain.py doctor [--json]
  uma linha por item: "OK|AVISO|ERRO <item> — <detalhe>"
  itens: configuração local, vault, files, brain-config.yml (versão e chaves), pastas do layout, contextos,
         processadores (executável no PATH), provider (aviso sobre celular do providers.md)
  exit 0 sem ERRO; 1 com ERRO; 3 sem configuração local (mesma mensagem do config)

Validação do brain-config.yml (v2): todo valor de layout, para e contexts.<c>.folder é relativo e fica dentro do
  vault (sem caminho absoluto nem ".."); violação → os comandos saem com 1 "brain-config.yml: <chave> fora do vault"
  e o doctor mostra ERRO nessa chave. brain-config.yml que não é lido → doctor mostra "ERRO brain-config.yml —
  <erro de leitura>" e continua os demais itens.

references/providers.md (v2): só afirma o que está na fonte verificada do ADR-0008; o resto é marcado como
  orientação geral não verificada.

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
| Caminho fora do vault (v2) | `layout.log: ../x.md`, `/abs`, contexto com `..` | exit 1 com a chave; nada escrito fora | UT-07, IT-11 |
| Adopt com log do usuário (v2) | vault com `log.md` próprio | exit 2; `log.md` intacto | IT-08 |
| Pasta não vazia sem adopt (v2) | `init` em pasta com notas | exit 2 sugerindo `--adopt` | IT-09 |
| Comentários preservados (v2) | `context add` em arquivo comentado, indentação de 4, contexts inline | comentários intactos; indentação seguida; inline → exit 2 | IT-10 |
| Config malformado (v2) | aspas não fechadas no `brain-config.yml` | doctor com ERRO nessa linha e os outros itens | IT-11 |

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

- **UT-07** — (v2) Dado um `brain-config.yml` com `layout.log: ../x.md`, outro com `layout.inbox: /abs/inbox` e outro com `contexts.c.folder: ../../fora`, quando `load_config` roda, então falha nomeando a chave; com valores relativos válidos, passa.

### 7.3 Testes de Integração
- **IT-01** — Dado um diretório temporário vazio e `BRAIN_CONFIG_HOME` isolado, quando roda `brain.py init --vault V --files F --provider google-drive --context college=projects/college:College`, então V tem toda a estrutura do contrato, `brain-config.yml` tem o contexto, a configuração local tem os caminhos, `log.md` tem a linha de `init` e o exit é 0.
- **IT-02** — Dado um vault com `Inbox/a.md`, `Notas/b.md` e `.obsidian/`, quando roda `init --adopt --map inbox=Inbox`, então o conteúdo e a data de modificação de `a.md`, `b.md` e `.obsidian/` não mudam, nenhuma pasta de PARA é criada, `layout.inbox` é `Inbox` e são criados só `raw/`, `templates/`, `index.md`, `log.md` e `brain-config.yml`.
- **IT-03** — Dado um vault já criado, quando roda `init` de novo igual, então imprime "Vault já configurado"; com `brain-config.yml` alterado à mão e sem `--force`, sai com 2; com `--force`, cria `brain-config.yml.bak` com o conteúdo anterior.
- **IT-04** — Dado o vault do IT-01 e uma segunda `BRAIN_CONFIG_HOME` com outro caminho para o mesmo vault (link simbólico), quando roda `init --join`, então só a configuração local é gravada e `config --json` mostra os mesmos contextos nas duas; num vault sem `brain-config.yml`, `--join` sai com 2.
- **IT-05** — Dado `BRAIN_CONFIG_HOME` vazio, quando roda `config` e `doctor`, então os dois saem com 3 e a mensagem "second-brain não configurado nesta máquina — rode init (ou init --join)".
- **IT-06** — Dado o vault do IT-01 com um processador `pdf` cujo executável não existe, quando roda `doctor`, então os itens de configuração são OK, o processador é AVISO e o exit é 0; depois de remover a pasta do vault, `doctor` mostra ERRO no vault, sai com 1 e não imprime traceback.
- **IT-07** — Dado o vault do IT-01, quando roda `context add work --folder areas/work --title Work`, então o contexto entra no `brain-config.yml`, `areas/work/` e `mocs/work.md` existem e `log.md` registra; repetir o comando sai com 2.

- **IT-08** — (v2) Dado um vault com `log.md` escrito pelo usuário e sem `brain-config.yml`, quando roda `init --adopt`, então sai com 2 com a mensagem do contrato e `log.md` e o resto do vault não mudam; com `--map log=brain-log.md`, conclui e cria `brain-log.md`.
- **IT-09** — (v2) Dado uma pasta com notas e sem `brain-config.yml`, quando roda `init` sem `--adopt`, então sai com 2 sugerindo `--adopt` e nada é criado.
- **IT-10** — (v2) Dado um `brain-config.yml` com comentários e entradas de `contexts` indentadas com 4 espaços, quando roda `context add work --folder areas/work`, então os comentários continuam iguais e a entrada nova usa 4 espaços; com `contexts: {college: {folder: projects/college}}`, sai com 2 e o arquivo não muda. O `brain-config.yml` gerado pelo `init` mantém os comentários do modelo da skill.
- **IT-11** — (v2) Dado um `brain-config.yml` com `layout.log: ../escaped.md`, quando roda `context add` e `doctor`, então `context add` sai com 1 e nada é criado fora do vault, e o `doctor` mostra ERRO em `layout.log`; com aspas não fechadas, o `doctor` mostra "ERRO brain-config.yml — …" e ainda lista os itens de configuração local e vault.

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
- [x] Red: UT-06, UT-04 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [x] Green: `tests/test_architecture.py` com as regras do ADR-0007; `brain.py` com `argparse` e parser/escritor de YAML
- [x] Refactor mantendo tudo verde

**Fase 2: Configuração em duas camadas**
- [x] Red: UT-01, UT-02, UT-03, IT-05 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [x] Green: `load_config` com origem dos valores; validação de `init`; `config`
- [x] Refactor mantendo tudo verde

**Fase 3: Onboarding e doctor**
- [x] Red: IT-01, IT-02, IT-03, IT-04, IT-06, IT-07 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [x] Green: `init` (novo, `--adopt`, `--force`, `--join`), `context add`, `doctor`, modelos em `assets/`
- [x] Refactor mantendo tudo verde

**Fase 4: Instruções, CI e docs**
- [x] Red: UT-05 com a tag `SPEC-0017:<ID>`, falhando pelo motivo certo
- [x] Green: `SKILL.md`, `references/config.md`, `providers.md`, `vault-layout.md`; passo da suíte nova em `.github/workflows/ci.yml`; README e CHANGELOG raiz
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [x] Architect: `test` e `arch_test` do `docs/specs/sdd-config.yml` passam a incluir `skills/second-brain/tests`

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [x] Relatório de Entrega, docs raiz e CHANGELOG (G7) — CHANGELOG da skill; não há CHANGELOG na raiz do repositório

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=25)) — 08d9ab7 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 1dc7044 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1dc7044 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (1dc7044; 3 minor: vault só com .obsidian recusado sem --adopt; mensagem do IT-08 cita só a chave em colisão; brain.py executável) — 1dc7044 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 70bac4d | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 2ae3b08 | 2026-10-30 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-30 | G4 | spec | Contrato não cobre: init sem --adopt em pasta não vazia; --adopt com log.md/index.md do usuário; valores de layout/para/contexts fora do vault vindos do brain-config.yml; context add com contexts inline; doctor com brain-config.yml malformado; formato da linha de log diverge da SPEC-0019 | Review G4 (CHANGES_REQUESTED) reproduziu escrita fora do vault, append em log.md do usuário e perda de comentários | Architect + thomas (Emenda v2) | Emenda v2 — contrato cobre os casos do review G4; aprovada por thomas em 2026-10-30 | 2026-10-30 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
A skill `second-brain` existe, com a base para as outras filhas do épico SPEC-0016:
- estrutura do vault em inglês;
- configuração em duas camadas: `brain-config.yml` no vault e `config.yml` local por máquina, com `BRAIN_CONFIG_HOME`;
- onboarding não interativo (`init`, com vault novo, `--adopt`, `--map`, `--context`, `--force` e `--join`);
- `config`, `context add` e `doctor`.

O `SKILL.md` manda o agente rodar `brain.py config` antes de qualquer fluxo. Sem configuração, ele conduz o onboarding; com configuração, segue direto. A CI roda a suíte nova, e o README lista a skill.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `skills/second-brain/scripts/brain.py`: arquivo único só com a biblioteca padrão (ADR-0007), com `BRAIN_VERSION` 2026.10.1. Tem parser e escritor de YAML próprios (`parse_yaml`, `dump_yaml`), `read_config`/`load_config` com a origem de cada valor e validação de caminhos dentro do vault (Emenda v2). Toda escrita passa por funções que nunca sobrescrevem e acrescentam uma linha `- AAAA-MM-DD HH:MM …` no `log.md`.
- O `brain-config.yml` é gerado a partir do texto de `assets/brain-config.yml`, mantendo os comentários. O `context add` só insere linhas, com a indentação existente.
- Também foram criados `assets/templates/` (7 tipos), `SKILL.md`, `references/config.md`, `references/providers.md` (só fatos verificados do ADR-0008, com o resto marcado como não verificado), `references/vault-layout.md`, `CHANGELOG.md` da skill, o passo na CI e a linha no README.
- **Emenda v2 (IMP-01):** a primeira revisão G4 reproduziu três problemas: escrita fora do vault, linha acrescentada no `log.md` do usuário e perda de comentários. O contrato ganhou as regras e os testes UT-07 e IT-08 a IT-11. Uma nova rodada de red (ce9c634) veio antes da correção (25ceba8, 1dc7044), e a revisão seguinte aprovou.
- **Desvios aceitos na revisão:**
  - `.DS_Store`, `Thumbs.db` e `desktop.ini` não contam como conteúdo;
  - qualquer `..` é recusado;
  - a recusa de `log.md` ou `index.md` do usuário vale também para `init` comum e `--force`;
  - a mensagem do IT-08 cita só a chave em colisão (`--map log=…` ou `--map index=…`);
  - `brain.py` é executável, como o `spec_graph.py`.
- O lint passou a rodar localmente com o uv, instalado pelo Homebrew por decisão do usuário.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Configuração efetiva com a origem de cada valor | PASS | `test_config.py::LoadConfigTest.test_effective_config_reports_the_origin_of_each_value` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-02 | Validação de files e provider no init | PASS | `test_config.py::ValidateInitArgsTest (3 testes); test_cli.py::InitArgsCliTest.test_invalid_init_arguments_exit_2_with_the_message` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-03 | brain-config.yml sem caminho absoluto | PASS | `test_config.py::BrainConfigWithoutAbsolutePathsTest.test_generated_brain_config_has_no_absolute_path` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-04 | Parser e escritor de YAML | PASS | `test_config.py::YamlTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-05 | Instruções de onboarding, configuração e provedores | PASS | `test_instructions.py::InstructionsTest (3 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-06 | Regras de arquitetura do ADR-0007 | PASS | `test_architecture.py::ImportRulesTest, ProcessRulesTest, PersonalPathRulesTest (7 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| UT-07 | Valores do brain-config.yml fora do vault recusados (v2) | PASS | `test_amendment_v2.py::OutsideVaultLoadConfigTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | Vault novo com estrutura, duas configurações e log | PASS | `test_cli.py::NewVaultTest.test_init_creates_the_full_structure_and_both_configs` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-02 | Adotar vault sem alterar arquivos | PASS | `test_cli.py::AdoptVaultTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-03 | init repetido, config diferente e --force com backup | PASS | `test_cli.py::ReinitTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-04 | init --join numa máquina nova | PASS | `test_cli.py::JoinTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-05 | Sem configuração local: exit 3 | PASS | `test_cli.py::NotConfiguredTest.test_config_and_doctor_without_local_config_exit_3` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-06 | doctor saudável e com erro, sem traceback | PASS | `test_cli.py::DoctorTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-07 | context add e contexto repetido | PASS | `test_cli.py::ContextAddTest.test_context_add_registers_creates_folder_and_moc_and_logs` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-08 | Adopt recusa log.md/index.md do usuário (v2) | PASS | `test_amendment_v2.py::AdoptWithUserLogTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-09 | Pasta não vazia sem --adopt recusada (v2) | PASS | `test_amendment_v2.py::NotEmptyWithoutAdoptTest.test_init_in_a_folder_with_notes_suggests_adopt_and_creates_nothing` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-10 | Comentários e indentação preservados; contexts inline recusado (v2) | PASS | `test_amendment_v2.py::CommentsPreservedTest (3 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |
| IT-11 | Caminho fora do vault e config malformado no doctor (v2) | PASS | `test_amendment_v2.py::ValidationAndMalformedTest (2 testes)` — CI do PR #15 em 70bac4d (run 41043522848, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — `doctor` e `config` em 0,08–0,13 s com 5.000 notas (meta: menos de 1 s); segurança e privacidade por UT-03, UT-07, IT-08 a IT-11
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado; vale na `main` com o merge do PR #15
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: sem `living_docs` configurado
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15; quem usa copia `skills/second-brain/` para o diretório de skills. Versão da skill: 2026.10.1. Rollback: revert do merge.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
SPEC-0025 — vault criado pelo app do Obsidian, só com `.obsidian/`, deve receber a estrutura padrão (achado minor 1 da revisão G4). A spec está proposta e aguarda aprovação.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0017`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-30 | `init` recusa pasta não vazia sem `--adopt` e `log`/`index` do usuário no `--adopt`; validação de `layout`/`para`/`contexts` dentro do vault; `context add` nunca reescreve o arquivo e segue a indentação; `doctor` continua com config malformado; log com `- ` (como na SPEC-0019); `brain-config.yml` gerado com comentários; `providers.md` só com fatos verificados. Testes UT-07, IT-08 a IT-11. | Review G4 (IMP-01): escrita fora do vault, append no `log.md` do usuário e perda de comentários reproduzidos; contrato não cobria esses casos | Nenhuma (nenhuma spec consome o contrato da SPEC-0017) | thomas (2026-10-30) |
