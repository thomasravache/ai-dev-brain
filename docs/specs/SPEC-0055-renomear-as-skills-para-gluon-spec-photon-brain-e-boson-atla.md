---
id: SPEC-0055
title: Renomear as skills para gluon-spec, photon-brain e boson-atlas
tier: full
type: migration
user_facing: false
status: in-progress
created: 2026-11-12
parent: SPEC-0031
depends_on: [SPEC-0029]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/**, .github/workflows/ci.yml, README.md, AGENTS.md, tests/plugin/test_skill_names.py]
adrs: [ADR-0018]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-12
---

# SPEC-0055 — Renomear as skills para gluon-spec, photon-brain e boson-atlas

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
As três skills ganham os nomes da marca Fermion antes da primeira publicação do plugin: `sdd-management` → `gluon-spec`, `second-brain` → `photon-brain`, `org-atlas` → `boson-atlas`. Mudam a pasta, o `name` do `SKILL.md` e os textos que apresentam a skill; o plugin passa a mostrar `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas`. Tudo o que outros projetos, máquinas e atlas já usam (scripts, pastas de configuração, contratos, arquivos gerados) fica como está.

## 2. Motivação & Escopo
**Motivação:** o nome da pasta vira o comando do plugin. Renomear depois de publicar o `fermion` faria quem instalou perder os comandos que usa; antes da publicação, a troca não custa nada a quem usa o plugin (thomas, 2026-11-12).

**Objetivos (dentro do escopo):**
- `git mv` das três pastas em `skills/` e `name` do frontmatter igual à pasta nova.
- `description` de cada skill cita o nome antigo ("antes `sdd-management`"), para que agentes e blocos `AGENTS.md` já instalados que pedem o nome antigo achem a skill.
- Título e textos que apresentam a skill (`SKILL.md`, `references/`, CHANGELOG de cada skill com a entrada da troca), README (tabela de nomes vira nomes atuais, instalação por cópia com as pastas novas e aviso para quem já copiou), `AGENTS.md` e o modelo do bloco SDD (`assets/agents-snippet.md`), caminhos na CI e nas regras de arquitetura que citam as outras skills.
- Versão de cada skill sobe (`SDD_TOOL_VERSION`, `BRAIN_VERSION`, `ATLAS_VERSION`).

**Não-objetivos (fora do escopo):**
- Nomes de scripts (`spec_graph.py`, `brain.py`, `atlas.py`), pastas de configuração da máquina (`~/.config/second-brain`, `~/.config/org-atlas`, `$BRAIN_CONFIG_HOME`, `$ATLAS_CONFIG_HOME`), o contrato `org-atlas/collector@1`, a pasta `.org-atlas/` dos atlas, `tools/sdd/`, `docs/specs/sdd-config.yml`, o bloco `sdd:start`, nomes de backup e as mensagens das CLIs: tudo continua igual, para não quebrar dados, atlas e projetos existentes.
- Renomear o repositório (`ai-dev-brain` → `fermion-lab`); histórico em `docs/specs/`, `docs/adr/` e seções antigas dos CHANGELOGs.
- Apagar cópias antigas já instaladas em `~/.claude/skills/` (o README orienta).

## 3. Dependências
- **Implementações necessárias:** SPEC-0029 — as três skills na forma atual.
- **Contratos consumidos:** N/A.
- **Pré-requisitos externos:** nenhuma branch aberta mexendo em `skills/` (conferido em 2026-11-12: nenhum PR aberto); o Architect atualiza `test`/`arch_test` do `sdd-config.yml` e os `touches` das specs abertas no mesmo PR.

## 4. Decisão Arquitetural
**Contexto:** brownfield. As skills são pastas independentes (ADR-0001, ADR-0007, ADR-0010) que se citam por `<skill-dir>` e nunca por caminho fixo; os nomes foram escolhidos em 2026-10-30 e revistos em 2026-11-12 (SPEC-0031).

**Decisão:** renomear pasta, `name` e textos de apresentação; manter todo identificador que outro sistema guarda ou lê (ADR-0018). O nome antigo fica como apelido na `description`.

**Justificativa:** o comando do plugin vem da pasta; dados e contratos com nome antigo estão em máquinas, atlas e projetos fora do repositório, e mudá-los exigiria migração de dados sem ganho para o usuário.

**Desvio do padrão existente:** a troca de nome é a migração; regras de arquitetura e caminhos seguem iguais, só com os nomes novos (ADR-0018).

**Alternativas descartadas:** renomear depois da publicação, com apelidos (quebra comandos de quem instalou); renomear também scripts, pastas de configuração e contratos (migração de dados em toda máquina e atlas); só mudar o `name` do frontmatter sem a pasta (o plugin usa o nome da pasta no comando).

**ADRs:** ADR-0018.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A.
- **Segurança:** N/A — sem mudança de comportamento.
- **Privacidade e dados pessoais:** N/A.
- **Disponibilidade e resiliência:** máquinas, vaults e atlas já configurados continuam funcionando sem nenhuma ação (UT-04 garante os identificadores mantidos).
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** nomes das skills (pasta, `name`, `description`) e identificadores mantidos

```text
renomeado
  skills/sdd-management → skills/gluon-spec      name: gluon-spec     description cita "antes sdd-management"
  skills/second-brain   → skills/photon-brain    name: photon-brain   description cita "antes second-brain"
  skills/org-atlas      → skills/boson-atlas     name: boson-atlas    description cita "antes org-atlas"
  título do SKILL.md, references/ e textos que apresentam a skill usam o nome novo
  bloco SDD (assets/agents-snippet.md e AGENTS.md): "Carregue a skill `gluon-spec` (antes `sdd-management`)"
  CI e regras de arquitetura que citam outra skill usam os nomes novos (e continuam acusando os antigos)
  versões: SDD_TOOL_VERSION, BRAIN_VERSION e ATLAS_VERSION sobem; cada CHANGELOG tem "Changed: a skill passa a se chamar ..."

mantido (igual antes e depois)
  scripts: scripts/spec_graph.py, scripts/brain.py, scripts/atlas.py
  configuração da máquina: ~/.config/second-brain, ~/.config/org-atlas, BRAIN_CONFIG_HOME, ATLAS_CONFIG_HOME
  contrato dos coletores: "org-atlas/collector@1"; pasta .org-atlas/ do atlas
  projetos: tools/sdd/, docs/specs/sdd-config.yml, bloco sdd:start
  mensagens e saídas das CLIs (incluindo --version e nomes de backup)

referência velha
  fora de docs/specs/, docs/adr/, seções antigas dos CHANGELOGs e dos identificadores mantidos,
  nenhum arquivo do repositório cita skills/sdd-management, skills/second-brain ou skills/org-atlas → senão a suíte falha
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. `git mv` das três pastas; textos citados no contrato; `.github/workflows/ci.yml`; `README.md`; `AGENTS.md`; `tests/plugin/test_skill_names.py` (novo).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Comportamento atual preservado | suítes das três skills | passam antes e depois da troca | CH-01, IT-01 |
| Pastas e nomes novos | `skills/` | só as três pastas novas; `name` igual à pasta | UT-01 |
| Apelido do nome antigo | `description` e bloco SDD | citam o nome antigo | UT-02 |
| Sem referência velha | arquivos fora da lista de exceções | nenhum caminho `skills/<nome antigo>`; exemplo com referência velha é acusado | UT-03 |
| Identificadores mantidos | pastas de configuração, contrato, `.org-atlas/`, scripts | iguais aos de antes | UT-04 |
| Versões e CHANGELOG | as três skills | versão nova e entrada da troca em cada CHANGELOG | UT-05 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — As suítes das três skills passam no código atual, antes de qualquer mudança (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `skills/`, quando é listado, então tem exatamente `gluon-spec`, `photon-brain` e `boson-atlas`, cada uma com `SKILL.md` cujo `name` é igual à pasta.
- **UT-02** — Dado o `SKILL.md` de cada skill e o `assets/agents-snippet.md` da `gluon-spec`, quando são lidos, então a `description` cita o nome antigo da skill e o bloco SDD diz "`gluon-spec` (antes `sdd-management`)".
- **UT-03** — Dados os arquivos versionados fora de `docs/specs/`, `docs/adr/` e das seções antigas dos CHANGELOGs, quando a busca por `skills/sdd-management`, `skills/second-brain` e `skills/org-atlas` roda, então não há ocorrência; um arquivo de exemplo com uma dessas referências é acusado.
- **UT-04** — Dados os scripts das três skills, quando os identificadores mantidos são conferidos, então `~/.config/second-brain`, `~/.config/org-atlas`, `BRAIN_CONFIG_HOME`, `ATLAS_CONFIG_HOME`, `org-atlas/collector@1` e `.org-atlas/` continuam presentes, e os scripts mantêm os nomes `spec_graph.py`, `brain.py` e `atlas.py`.
- **UT-05** — Dadas as três skills, quando a versão e o CHANGELOG são lidos, então a versão é maior que a de antes da troca (`SDD_TOOL_VERSION` 2026.11.1, `BRAIN_VERSION` 2026.11.5 e `ATLAS_VERSION` 2026.11.2) e o CHANGELOG tem a entrada "passa a se chamar".

### 7.3 Testes de Integração
- **IT-01** — Dadas as pastas renomeadas, quando as suítes completas (`python3 -m unittest discover -s skills/<nome>/tests`) e os testes de arquitetura das três rodam, então passam como antes.

### 7.4 Testes de Contrato
- N/A — os contratos entre skills e com projetos (identificadores mantidos) são cobertos pelo UT-04.

### 7.5 Testes E2E
- N/A — nenhuma jornada muda além do nome; a instalação pelo plugin com os nomes novos é provada pela SPEC-0053 (E2E-01).

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** arquivo de exemplo com referência velha em pasta temporária.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, junto com o primeiro release do plugin.
- **Dados/schema:** N/A — nenhum dado muda de lugar.
- **Compatibilidade:** quem copiou as pastas antigas para `~/.claude/skills/` continua com elas funcionando; o README orienta apagar e instalar o plugin (ou copiar as pastas novas). Projetos com o bloco SDD antigo continuam achando a skill pelo apelido na `description`.
- **Observabilidade:** N/A.
- **Rollback:** reverter o merge (o `git mv` volta inteiro).
- **Etapas de migração/coexistência:** apelido na `description` por tempo indeterminado; remoção, se houver, é outra spec.

## 9. Questões em Aberto
- [x] Renomear antes ou depois do plugin? — Antes, para o plugin já sair com os nomes finais (thomas, 2026-11-12)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [ ] CH-01: suítes das três skills verdes antes da troca (guarda)

**Fase 1: Troca de nomes**
- [ ] Red: UT-01 a UT-05 em `tests/plugin/test_skill_names.py` com a tag `SPEC-0055:<ID>`, falhando pelo motivo certo
- [ ] Green: `git mv` das pastas, `name`/`description`, textos, bloco SDD, CI, regras de arquitetura, versões e CHANGELOGs
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suítes das três skills (IT-01), lint e arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Architect: `test`/`arch_test` do `sdd-config.yml` e `touches` das specs abertas com os caminhos novos
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, README e CHANGELOGs (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 997634e (árvore suja) | 2026-11-12 |
| G1 Red | FAIL | verify G1: FAIL — testes do plano sem tag no código versionado: SPEC-0055:CH-01, SPEC-00; nota: vermelho conferido pelo Test-writer em c6f89ba: test_skill_names.py 6 testes, 14 falhas (pastas novas inexistentes, 26 referências velhas); CH-01 guarda: suítes atuais verdes (sdd 164 OK, second-brain 334 OK, org-atlas 333 OK) — c6f89ba | 2026-11-12 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0055`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
