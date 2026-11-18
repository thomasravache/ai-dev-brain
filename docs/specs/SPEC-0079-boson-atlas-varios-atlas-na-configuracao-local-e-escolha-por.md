---
id: SPEC-0079
title: "boson-atlas: vários atlas na configuração local e escolha por --atlas"
tier: full
type: feature
user_facing: true
status: approved
created: 2026-11-18
parent: SPEC-0077
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/config.md, skills/boson-atlas/references/modes.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0020, ADR-0021]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-18
---

# SPEC-0079 — boson-atlas: vários atlas na configuração local e escolha por --atlas

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
A configuração local da `boson-atlas` passa a guardar vários atlas com nome, cada um com as suas credenciais. Todos os comandos escolhem um deles por uma ordem fixa: `--atlas`, `ATLAS_NAME`, `default` e atlas único (o passo do remote do projeto vem na SPEC-0080). Quem tem um atlas só continua com o mesmo arquivo e os mesmos comandos.

## 2. Motivação & Escopo
**Motivação:** hoje a máquina tem um atlas só. Trocar de organização exige outro `ATLAS_CONFIG_HOME` e lembrar de exportá-lo, e um `init --join` regrava o ponteiro e perde o atlas anterior (SPEC-0077).

**Objetivos (dentro do escopo):**
- Ler a forma nova (`default:` + `atlases:`) e a forma de um atlas só (`atlas:` + `credentials:`).
- Ordem de escolha `--atlas` → `ATLAS_NAME` → `default` → atlas único, usada por `scan`, `build`, `context`, `curate`, `vendor`, `lint`, `config` e `doctor`.
- `init` e `init --join` com `--name` e `--default`, acrescentando sem apagar os outros.
- `config --list` e `config --set-default`.
- `doctor` com a lista dos atlas, e campos novos no `config --json`.

**Não-objetivos (fora do escopo):**
- Escolha pelo remote do projeto, `remotes:`, MCP e hook: SPEC-0080.
- `org_context` da `gluon-spec`: SPEC-0081.
- Remover atlas da lista. A pessoa edita o arquivo; o `doctor` avisa quando a pasta de um atlas não existe mais.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** segue a configuração de duas camadas do `atlas.py`: `local_config_path`, `local_config_write_path`, `read_local`, `load_config`, `render_local_config`, `write_local_config`, `existing_credentials`, `scan_config`, `_lint_atlas`, `cmd_init`/`join_atlas` e `doctor_rows`. Segue também os testes de `tests/test_config.py` e `tests/test_rename.py` com o `Sandbox` de `tests/helpers.py`.

**Decisão:**
- Uma função `select_atlas` resolve a entrada escolhida a partir da configuração lida, das opções e do ambiente.
- `scan_config`, `_lint_atlas`, `load_config` e `doctor_rows` passam a usar essa entrada em vez de `local["atlas"]`.
- A escrita mantém a forma de um atlas só enquanto houver uma entrada.

**Justificativa:** um ponto único de escolha evita que um comando use um atlas e outro comando use outro (ADR-0021). Manter a forma antiga com uma entrada preserva o rollback e as máquinas de quem não usa várias organizações (ADR-0020).

**Desvio do padrão existente:** nenhum. A regra de "um atlas por máquina" do ADR-0010 é revisada pelo ADR-0021, e as demais regras (credenciais só pelo nome, nada absoluto no arquivo compartilhado, stdlib) continuam.

**Alternativas descartadas:**
- **Um `ATLAS_CONFIG_HOME` por organização** (o que existe hoje): obriga a exportar a variável e não deixa o hook nem o MCP escolherem.
- **Gravar sempre a forma nova:** quebra o rollback de quem tem um atlas só.
- **Nome automático pela pasta:** pastas como `atlas` se repetem entre organizações.

**ADRs:** ADR-0021 (criado pelo épico), ADR-0010, ADR-0020.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — leitura de um arquivo pequeno e de um `atlas-config.yml` por atlas só no `config --list` e no `doctor`.
- **Segurança:** as credenciais de um atlas nunca são usadas por outro. O `scan` e o `doctor` leem só as do atlas escolhido (IT-02). O arquivo local continua só com nomes de credenciais (validação existente).
- **Privacidade e dados pessoais:** mensagens de erro e o `config --list` mostram nome e caminho do atlas só para a própria pessoa, na máquina dela. Nenhuma saída nova inclui valores de credenciais.
- **Disponibilidade e resiliência:** a forma antiga continua lida e gravada com uma entrada (IT-01). A escrita é atômica (`.tmp` + `os.replace`, padrão existente) e grava `.bak` ao mudar de forma.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** configuração local `~/.config/boson-atlas/config.yml` (ou `$ATLAS_CONFIG_HOME/config.yml`), opção `--atlas`, variável `ATLAS_NAME`, `init`, `config` e `doctor`.

```text
Configuração local — forma de vários atlas (contrato SPEC-0079@1)
  default: <nome>              # opcional; precisa existir em atlases
  atlases:
    <nome>:                    # [a-z0-9][a-z0-9-]{0,62}
      atlas: <caminho absoluto>
      credentials: {...}       # mesmo formato de hoje, só nomes
Forma de um atlas só (continua válida): atlas: <caminho> + credentials: {...}
  nome dessa entrada = organization do seu atlas-config.yml em minúsculas, com o que não for [a-z0-9-] trocado
  por "-" (vazio ou ilegível → "default")
As duas formas no mesmo arquivo, nome inválido, default sem entrada ou chave desconhecida → exit 2

Ordem de escolha (todos os comandos menos init), a primeira que se aplica:
  1. --atlas <nome|caminho>  (caminho = contém "/" ou começa com "~" ou "."; casa pela pasta resolvida)
  2. ATLAS_NAME=<nome|caminho>
  3. (reservado: remote do projeto — SPEC-0080)
  4. default
  5. o único atlas configurado
  Nome ou caminho que não está na configuração → exit 3:
    "atlas não configurado nesta máquina: <x> — rode init --join --atlas <caminho> (atlas configurados: a, b)"
  Vários atlas e nenhuma escolha → exit 2:
    "vários atlas configurados (a, b) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou config --set-default <nome>"
  Nenhuma configuração → exit 3 (mensagem NOT_CONFIGURED de hoje)

init --atlas <caminho> --org O --mode M [--name N] [--default] [--force]
init --join --atlas <caminho> [--name N] [--default]
  - --name padrão = nome derivado da organization (regra acima); --name inválido → exit 2
  - acrescenta ou atualiza a entrada N; as outras entradas e suas credenciais não mudam
  - a primeira entrada vira default; --default torna N o default
  - N já usado por outro caminho, ou o mesmo caminho já configurado com outro nome → exit 2 com o nome/caminho em uso
  - mesmo N e mesmo caminho → atualiza (como o init/join de hoje), mantendo as credenciais da entrada
  - com 1 entrada no resultado, grava a forma de um atlas só; com 2 ou mais, a forma nova; ao passar da forma de
    um atlas só para a nova, grava config.yml.bak antes
  - demais regras do init (--org/--mode, --force, pasta não vazia, --join sem atlas-config.yml) não mudam

config [--json] [--atlas X]
  - texto: como hoje, para o atlas escolhido, mais a linha "atlas: <nome> (escolhido por: --atlas|ATLAS_NAME|default|único)"
  - --json: os campos de hoje ("values", "origins") mais "atlas_name", "selected_by"
    ("option" | "env" | "default" | "single") e "atlases": [{"name", "atlas", "default"}] (ordem por nome)
config --list [--json]
  - lista todos os atlas: nome, caminho, default, organization (do atlas-config.yml; "?" se ilegível)
    e qual seria escolhido agora e por quê; não falha com vários atlas sem escolha (só mostra "nenhum")
config --set-default <nome>
  - grava default; nome que não existe → exit 2; com uma entrada só, não muda o arquivo (já é o default)

doctor [--atlas X]
  - checa o atlas escolhido como hoje (ERRO como hoje)
  - linha "Atlas configurados: N (a, b)"; pasta de outro atlas que não existe → AVISO com o nome
  - vários atlas sem escolha → ERRO com a mensagem de escolha acima
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: leitura e validação da forma nova, `select_atlas`, os pontos que hoje usam `local["atlas"]`, `init`/`join_atlas`, `config` e `doctor`, e `ATLAS_VERSION`.
- `references/config.md` e `references/modes.md`: o formato, a ordem e o onboarding com duas organizações.
- `SKILL.md`: a linha de comandos.
- `CHANGELOG.md` e o `plugin.json`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Forma antiga | `atlas:` + `credentials:` da versão anterior | todos os comandos iguais a hoje; nome derivado da organization | CH-01, UT-01, IT-01 |
| Forma nova | `default:` + `atlases:` válidos | entrada do `default` usada por todos os comandos | UT-01, UT-03 |
| Forma inválida | as duas formas juntas, nome inválido, `default` inexistente, chave desconhecida | exit 2 com a chave | UT-02 |
| Escolha por opção ou ambiente | `--atlas nome`, `--atlas caminho`, `ATLAS_NAME` | a opção vence o ambiente, que vence o `default`; `selected_by` certo | UT-03, E2E-01 |
| Escolha desconhecida | `--atlas`/`ATLAS_NAME` com nome ou caminho fora da lista | exit 3 com a lista e o passo | UT-04 |
| Sem escolha | vários atlas, sem `default` nem opção | exit 2 com a lista e os três passos; `config --list` não falha | UT-04 |
| Acrescentar atlas | `init`/`init --join` com outro caminho e nome | entrada nova, outras intactas, forma nova e `.bak` | UT-05, IT-01, E2E-01 |
| Conflito no init | nome em uso por outro caminho, ou caminho já com outro nome | exit 2 sem mudar o arquivo | UT-06 |
| Repetir join | mesmo nome e caminho | atualiza; com uma entrada continua na forma antiga | IT-01 |
| Trocar padrão | `config --set-default b` | `default: b`; nome inexistente → exit 2 | UT-07 |
| Credenciais isoladas | `scan` e `doctor` do atlas b | só as credenciais de b são lidas e checadas | IT-02 |
| Doctor | vários atlas, um com pasta ausente | linha de atlas configurados e AVISO com o nome | UT-08 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dada uma configuração de um atlas só criada pelo `init` atual (com `ATLAS_CONFIG_HOME` e na pasta padrão), quando `config --json`, `context`, `lint` e `init --join` no mesmo atlas rodam, então a saída e o arquivo gravado são os de hoje (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dada a forma de um atlas só, quando a configuração é lida, então há uma entrada com nome derivado da organization (`Acme Corp` → `acme-corp`; ilegível → `default`), que é a escolhida (`selected_by: single`).
- **UT-02** — Dadas as duas formas no mesmo arquivo, um nome fora de `[a-z0-9][a-z0-9-]{0,62}`, um `default` sem entrada ou uma chave desconhecida dentro de uma entrada, quando a configuração é lida, então exit 2 com a chave.
- **UT-03** — Dados os atlas `a` (default) e `b`, quando o comando roda sem opção, com `ATLAS_NAME=b`, com `--atlas b` e `ATLAS_NAME=a`, ou com `--atlas <caminho de b>` (relativo e com `~`), então é escolhido `a` (`default`), `b` (`env`), `b` (`option`) e `b` (`option`).
- **UT-04** — Dados os atlas `a` e `b` sem `default`, quando o comando roda sem escolha, então exit 2 com `a, b` e os três passos. Com `--atlas c` ou com um caminho não configurado, exit 3 com a lista. `config --list` sai 0 e mostra "nenhum".
- **UT-05** — Dada uma configuração de um atlas só (`a`), quando `init --join --atlas <outro> --name b` roda, então o arquivo passa à forma nova com `a` (default, mesmas credenciais) e `b`, e `config.yml.bak` guarda a forma antiga. Com `--default`, o default passa a ser `b`.
- **UT-06** — Dados os atlas `a` e `b`, quando o `init --join` usa `--name a` com o caminho de `b`, ou o caminho de `a` com `--name c`, então exit 2 com o nome ou o caminho em uso, e o arquivo não muda.
- **UT-07** — Dados os atlas `a` (default) e `b`, quando `config --set-default b` roda, então `default: b`; com `config --set-default c`, exit 2 e o arquivo não muda.
- **UT-08** — Dados os atlas `a` e `b`, com a pasta de `b` removida, quando o `doctor` roda escolhendo `a`, então há a linha "Atlas configurados: 2 (a, b)", um AVISO citando `b` e nenhum ERRO por causa de `b`.

### 7.3 Testes de Integração
- **IT-01** — Com o CLI como processo e `HOME` temporário, a forma antiga sobrevive: `init` de um atlas, depois `init --join` no mesmo atlas, e o arquivo continua na forma antiga, igual byte a byte ao da versão atual. `init --join` de um segundo atlas passa à forma nova com `.bak`. Restaurar o `.bak` volta ao comportamento de um atlas só.
- **IT-02** — Dois atlas com coletores `generic` que declaram credenciais diferentes (`env A_TOKEN` em `a`, `env B_TOKEN` em `b`): `scan --atlas b` e `doctor --atlas b` checam só `B_TOKEN`, e nenhuma saída nem snapshot de `b` cita `A_TOKEN`.

### 7.4 Testes de Contrato
- **CT-01** — Dados dois atlas e cada forma de escolha, quando `config --json` roda, então os campos `atlas_name`, `selected_by` (`option`/`env`/`default`/`single`) e `atlases` seguem o contrato da seção 6, que as SPEC-0080 e SPEC-0081 consomem.

### 7.5 Testes E2E
- **E2E-01** — Jornada de quem trabalha para duas organizações, com o CLI como processo e `HOME` temporário:
  1. `init` do atlas da organização A;
  2. `init --join` do atlas da organização B com `--name b`;
  3. `config --list` mostra os dois com A como padrão;
  4. `context --atlas b` e `ATLAS_NAME=b context` usam o grafo de B;
  5. `context` sem opção usa A;
  6. `config --set-default b` e `context` sem opção passa a usar B.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- `HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários (`Sandbox` de `tests/helpers.py`), com `run_default` para a pasta padrão.
- Atlas em pastas temporárias e coletor `generic` com fixtures.
- Nunca o `~/.config` real nem rede.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin.
- **Dados/schema:** a forma nova do arquivo local só é gravada ao acrescentar o segundo atlas, com `.bak` da forma antiga.
- **Compatibilidade:**
  - a forma antiga continua lida e gravada;
  - o `config --json` só ganha campos;
  - o `org-atlas` continua lido como reserva (ADR-0020);
  - `ATLAS_CONFIG_HOME` continua sem reserva.
- **Observabilidade:** `config`, `config --list` e `doctor` dizem qual atlas foi escolhido e por quê.
- **Rollback:**
  - reverter o merge;
  - quem já tem dois atlas restaura o `config.yml.bak`, e o CHANGELOG mostra o passo.
- **Etapas de migração/coexistência:** N/A — sem migração automática (ADR-0019).

## 9. Questões em Aberto
- [x] Nome da entrada na forma antiga: pasta, organization ou fixo? — Organization em minúsculas com `-` (é o nome que a pessoa reconhece); `default` se o `atlas-config.yml` não puder ser lido (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Escolha por caminho fora da lista deve usar o atlas mesmo assim? — Não: exit 3 com o passo `init --join`. Usar um atlas sem entrada deixaria o `scan` sem credenciais declaradas e confundiria o `doctor` (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Precisa de comando para remover um atlas? — Não neste épico: a pessoa edita o arquivo (documentado em `config.md`), e o `doctor` avisa quando a pasta sumiu (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Nome da variável de ambiente? — `ATLAS_NAME`, no mesmo prefixo de `ATLAS_CONFIG_HOME` (recomendação do arquiteto, piloto automático; revisável no H1)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [ ] Fase 0: CH-01 escrito e passando no código atual, commitado antes de qualquer mudança
- [ ] Red: UT-01 a UT-08, IT-01, IT-02, CT-01 e E2E-01 com a tag `SPEC-0079:<ID>`, falhando pelo motivo certo
- [ ] Green: forma nova e `select_atlas` em `atlas.py`; `scan_config`, `_lint_atlas`, `load_config` e `doctor_rows` pela entrada escolhida; `init`/`join_atlas` com `--name`/`--default`; `config --list`/`--set-default`; `references/config.md`, `references/modes.md`, `SKILL.md`, CHANGELOG, `ATLAS_VERSION` e `plugin.json`
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega, docs e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 5c2e257 | 2026-11-18 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0079`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
