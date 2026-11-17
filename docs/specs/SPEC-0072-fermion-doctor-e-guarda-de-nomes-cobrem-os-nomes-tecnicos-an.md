---
id: SPEC-0072
title: fermion_doctor e guarda de nomes cobrem os nomes técnicos antigos
tier: lite
type: feature
user_facing: false
status: implemented
created: 2026-11-16
parent: SPEC-0067
depends_on: [SPEC-0069, SPEC-0070, SPEC-0071]
consumes_contract: []
touches: [scripts/fermion_doctor.py, tests/plugin/**, hooks/session_start.py, README.md, .claude-plugin/plugin.json, mcp/tests/test_brain_server.py, mcp/tests/helpers.py, skills/gluon-spec/SKILL.md, skills/gluon-spec/references/brownfield.md, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/tests/**, skills/photon-brain/tests/test_architecture.py, skills/boson-atlas/references/config.md, skills/boson-atlas/references/modes.md]
adrs: [ADR-0019, ADR-0020]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0072 — fermion_doctor e guarda de nomes cobrem os nomes técnicos antigos

## 1. Problema
Depois das SPEC-0069 a 0071, cada skill avisa no próprio `doctor` quando a máquina ou o atlas ainda usa um nome técnico antigo. Mas esse `doctor` só roda quando a pessoa pede. O `fermion_doctor`, que roda em todo início de sessão (SPEC-0061), não olha `~/.config/second-brain`, `~/.config/org-atlas` nem `.org-atlas/` no projeto, então a migração fica invisível. E a guarda de nomes do repositório (`tests/plugin/test_skill_names.py`, SPEC-0055) só procura o caminho velho das pastas de skill: um `~/.config/second-brain` novo no código passaria sem acusação.

## 2. Causa Raiz
`scripts/fermion_doctor.py` tem só as checagens da SPEC-0061 (cópias, `tools/sdd`, bloco `sdd:start`, atlas vendorizado), e a do atlas lê só `.org-atlas/skill`. O padrão `OLD_REF_RE` de `test_skill_names.py` exige `skills/` antes do nome e deixa de fora, de propósito, os identificadores técnicos que a SPEC-0055 manteve.

## 3. Mudança Proposta
- `fermion_doctor` ganha a checagem `old-config`: AVISO quando `~/.config/second-brain` ou `~/.config/org-atlas` existe (respeitando `BRAIN_CONFIG_HOME`/`ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` quando a skill respeita), com o comando de cópia da SPEC-0069/0070, e com "pode apagar" quando a pasta nova também existe.
- A checagem `stale-atlas` passa a olhar `.boson-atlas/skill` e `.org-atlas/skill`, e a nova `old-atlas-folder` avisa `.org-atlas/` no projeto com o passo de migração do `vendor`.
- Bloco do hook de início de sessão: uma linha por achado novo, dentro do limite de 1.500 caracteres que já existe.
- Guarda de nomes: passa a acusar os nomes técnicos antigos (`~/.config/second-brain`, `~/.config/org-atlas`, `.org-atlas/`, `org-atlas/collector@1`, `second-brain-` em nome de backup, `second-brain`/`org-atlas` em textos de saída) em todo arquivo versionado, com exceções estreitas e listadas: as constantes de leitura de compatibilidade, os avisos de migração, os CHANGELOGs, `docs/specs/`, `docs/adr/`, fixtures de compatibilidade nomeadas como tal e o `fermion_doctor` (que procura esses nomes de propósito).
- README: seção dos nomes antigos atualizada (o que já mudou e quando o antigo deixa de ser lido).
- **Não muda:** o `fermion_doctor` continua só lendo e avisando, sem processos nem rede, sempre exit 0 (ADR-0019); a regra de nomes de pasta de skill da SPEC-0055.

**Padrão seguido:** checagens e linhas `AVISO`/`OK` de `scripts/fermion_doctor.py` (SPEC-0061) e a busca com exemplo que viola + arquivos reais de `tests/plugin/test_skill_names.py` (SPEC-0055)

**Rollback:** reverter o commit; os avisos somem e nada na máquina foi alterado

**Outras ocorrências:** nenhuma além das skills cobertas pelas SPEC-0069 a 0071; a `gluon-spec` não tem nome técnico antigo (o `sdd-management` só aparece como cópia instalada, já coberta pela SPEC-0061)

## 4. Plano de Testes (TDD)
- **CH-01** — Dado um ambiente temporário sem nada antigo (guarda: passa antes da mudança), quando o `fermion_doctor` roda, então a saída de hoje é mantida, com uma linha `OK` a mais por checagem nova depois da mudança.
- **UT-01** — Dados `HOME` e `XDG_CONFIG_HOME` temporários com `~/.config/second-brain`, depois com as duas pastas, e o mesmo para `org-atlas`, quando o `fermion_doctor --json` roda, então há o achado `old-config` com o comando de cópia (`cp -p`) no primeiro caso e "pode apagar" no segundo; com `BRAIN_CONFIG_HOME`/`ATLAS_CONFIG_HOME` definidos, nenhum achado.
- **UT-02** — Dado um projeto com `.org-atlas/skill` velho e outro com `.boson-atlas/skill` velho, quando o `fermion_doctor` roda, então `stale-atlas` acusa os dois e `old-atlas-folder` acusa só o primeiro.
- **UT-03** — Dado um exemplo com cada nome técnico antigo fora das exceções e as exceções listadas, quando a guarda de nomes roda, então acusa cada uso fora das exceções com `arquivo:linha` e nenhum dentro delas; nos arquivos versionados reais, depois das SPEC-0069 a 0071, nenhum achado.
- **UT-04** — (Emenda v2) Dado o servidor MCP rodando as tools `brain_*` com `HOME` temporário, quando as tools de leitura rodam, então nem `~/.config/second-brain` nem `~/.config/photon-brain` são criadas ou alteradas (hoje o teste só confere a pasta antiga).
- **IT-01** — Dado um ambiente temporário com `~/.config/second-brain` e um projeto com `.org-atlas/`, quando o hook de início de sessão roda como o Claude Code o chama, então o bloco "Instalação desatualizada (fermion)" traz uma linha para cada um, dentro de 1.500 caracteres.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Fase 1 (test-writer): CH-01, UT-01 a UT-04 e IT-01 com a tag `SPEC-0072:<ID>`, falhando pelo motivo certo
- [x] Fase 2 (implementer): checagens `old-config` e `old-atlas-folder`, `stale-atlas` nas duas pastas, bloco do hook, guarda de nomes com exceções listadas, README e versão do plugin
- [x] Fase 3 (reviewer): G4 independente

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 (árvore suja) | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=12)) — 089d8a3 | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — b75f949 | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 18dfd31 | 2026-11-17 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (rodada 2; blocker do Python 3.12+ e minors 2–8 resolvidos, provados em 3.9 e 3.14; guarda sem falso positivo nos arquivos reais; 2 nits aceitos) — 6b6bf41 | 2026-11-17 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — a8e52fe | 2026-11-17 |
| H2 Integração aprovada | PASS | aprovado por política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-17 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-17 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 549998f | 2026-11-17 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-17 | G1 | spec | guarda de nomes acha usos reais fora do touches: gluon-spec SKILL.md:168 e references/brownfield.md:31 citam ~/.config/org-atlas como pasta do atlas; collector-contract.md:5 descreve o snapshot ao contrário; testes e fixtures com o nome antigo fora de tests/plugin | listar exceções estreitas; nenhuma cabe sem esconder referência errada | architect | Emenda v3 — touches inclui gluon-spec SKILL.md/brownfield.md, collector-contract.md e testes/fixtures; exceções estreitas confirmadas | 2026-11-17 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- O `fermion_doctor`, que roda em todo início de sessão, passa a avisar a configuração nas pastas antigas (`old-config`, com o comando `cp -p` ou "pode apagar", inclusive quando a pasta antiga é link simbólico), a pasta `.org-atlas/` no projeto (`old-atlas-folder`) e a cópia velha da ferramenta nas duas pastas (`stale-atlas`). Uma guarda nova (`tests/plugin/test_old_technical_names.py`) acusa qualquer nome técnico antigo em arquivo versionado fora de exceções estreitas e listadas, lendo as strings dos scripts pela AST (igual do Python 3.9 ao 3.15). README, `gluon-spec/SKILL.md`, `brownfield.md` e referências da boson-atlas corrigidos. Plugin 2026.11.18.

### Como foi feito
- `old_config`/`old_atlas_folder` e `config_exists` em `scripts/fermion_doctor.py`; o hook de início de sessão não precisou mudar (já põe uma linha por achado, até 1.500 caracteres).
- Testes em 0615c77 (limpeza dos nomes antigos nos testes e fixtures), 089d8a3 e ae74063 (Emenda v4); implementação em 3c608b9 e b75f949.
- Impedimento IMP-01 (a guarda achou referências velhas reais na gluon-spec) resolvido pela Emenda v3; Emendas v4 e v5 pela revisão.
- **Revisão G4:** rodada 1 CHANGES_REQUESTED (guarda quebrava no Python 3.12+ e deixava passar f-strings; padrões e exceções largos; link simbólico) → Emendas v4 e v5; rodada 2 APPROVED, provada em 3.9 e 3.14.

### Prova de Correção
- **Antes:** 089d8a3 vermelho — 12 falhas em `tests/plugin` (sem `old-config`/`old-atlas-folder`, README e gluon-spec com referências velhas); ae74063 vermelho — 7 falhas (link simbólico, docs, notas de compatibilidade).
- **Depois:** 3c608b9 e b75f949 verdes; suíte completa no G5 (a8e52fe) e CI do PR (Python 3.9 e 3.15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Sem nada antigo, saída do doctor igual com linhas OK das checagens novas | PASS | `tests/plugin/test_fermion_doctor.py::OldNamesGuardTest` — G5 e CI do PR |
| UT-01 | `old-config` com `cp -p`, "pode apagar", link simbólico e sem achado com `*_CONFIG_HOME` | PASS | `tests/plugin/test_fermion_doctor.py::OldConfigTest` — G5 e CI do PR |
| UT-02 | `stale-atlas` nas duas pastas e `old-atlas-folder` só na antiga | PASS | `tests/plugin/test_fermion_doctor.py::OldAtlasFolderTest` — G5 e CI do PR |
| UT-03 | Guarda de nomes técnicos com exemplo e arquivos reais, nos dois Pythons | PASS | `tests/plugin/test_old_technical_names.py` — G5 e CI do PR |
| UT-04 | Tools `brain_*` do MCP não criam nem mudam as pastas de configuração | PASS | `mcp/tests/test_brain_server.py` — G5 e CI do PR |
| IT-01 | Hook de início de sessão com o bloco das checagens novas | PASS | `tests/plugin/test_fermion_doctor.py::OldNamesHookTest` — G5 e CI do PR |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — 089d8a3/ae74063 vermelhos, 3c608b9/b75f949 verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido — checagens da SPEC-0061 e busca com exemplo da SPEC-0055
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: plugin e cópias, sem deploy
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — README; CHANGELOGs das skills já registram as trocas (SPEC-0069 a 0071)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma

### Deploy
N/A — plugin 2026.11.18, PR desta spec.

### Pendências
- Nits da revisão, aceitos: `<antigo>-backup.zip` não é acusado (não é o formato real); a exceção E5 isenta a atribuição inteira das 6 constantes listadas.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v2 | 2026-11-17 | `touches` ganha `mcp/tests/test_brain_server.py` e o plano ganha UT-04 (o teste do MCP passa a conferir também `~/.config/photon-brain`); a guarda de nomes aceita como exceção as docstrings "formerly org-atlas/second-brain" dos scripts e os fixtures de compatibilidade (`tests/fixtures/previous/`, `old-contract-name.json`, `legacy_contract.py`) | achados das revisões das SPEC-0069 e 0071 | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v3 | 2026-11-17 | `touches` ganha `skills/gluon-spec/SKILL.md` e `skills/gluon-spec/references/brownfield.md` (passam a citar `~/.config/boson-atlas`, com a antiga como reserva), `skills/boson-atlas/references/collector-contract.md` (a nota do snapshot diz o contrário do código: o `scan` grava o nome antigo até a SPEC-0073), os testes e fixtures da `boson-atlas`, `skills/photon-brain/tests/test_architecture.py` e `mcp/tests/helpers.py`, que deixam de usar o nome antigo fora dos fixtures de compatibilidade (coletores falsos e snapshots de fixture passam a `boson-atlas/collector@1`; testes que precisam do antigo o montam por partes); a guarda não confere comentários nem docstrings dos scripts, e nos Markdown isenta só notas de compatibilidade que trazem o nome novo correspondente | impedimento IMP-01: a guarda encontrou referências velhas reais, que uma exceção esconderia | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v4 | 2026-11-17 | Guarda de nomes: strings dos scripts lidas pela AST (f-strings incluídas, igual do Python 3.9 ao 3.15); `folder` acusa também depois de `/`; `backup` acusa `second-brain-` seguido de `<`, fim de string ou concatenação nos scripts; `output` cobre `skills/*/scripts/**/*.py`, `skills/*/assets/**/*.py`, `skills/*/assets/**/*.sh` e `tools/sdd/*.py`; arquivo de texto não UTF-8 é lido com substituição; E6b exige "compatib" ou "nome antigo" no título e E6d exige "antig" junto do nome novo correspondente. `old-config` do `fermion_doctor` acusa a pasta antiga mesmo quando é link simbólico (só confere existência, como as skills). README, `gluon-spec/SKILL.md` e `brownfield.md` dizem "quando o `config.yml` da pasta nova não existe", e a nota do README cita o prefixo novo dos backups | G4 da SPEC-0072 (CHANGES_REQUESTED): a guarda falhava no Python 3.15 da CI e deixava passar f-strings e outros casos | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v5 | 2026-11-17 | `touches` ganha `skills/boson-atlas/references/config.md` e `modes.md`: com as exceções E6b/E6d mais estreitas da v4, a seção "Atlas com a pasta antiga" passa a ter "nome antigo" no título e as duas linhas da tabela de mensagens do `doctor` citam também o nome novo | as notas de compatibilidade legítimas deixavam de ser isentas, e corrigi-las é mais estreito que alargar a exceção | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
