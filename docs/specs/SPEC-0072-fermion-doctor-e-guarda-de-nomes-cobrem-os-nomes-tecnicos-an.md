---
id: SPEC-0072
title: fermion_doctor e guarda de nomes cobrem os nomes técnicos antigos
tier: lite
type: feature
user_facing: false
status: in-progress
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
- [ ] Fase 1 (test-writer): CH-01, UT-01 a UT-04 e IT-01 com a tag `SPEC-0072:<ID>`, falhando pelo motivo certo
- [ ] Fase 2 (implementer): checagens `old-config` e `old-atlas-folder`, `stale-atlas` nas duas pastas, bloco do hook, guarda de nomes com exceções listadas, README e versão do plugin
- [ ] Fase 3 (reviewer): G4 independente

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 (árvore suja) | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=12)) — 089d8a3 | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 3c608b9 | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 3b7fcb0 | 2026-11-17 |
| G4 Review | FAIL | CHANGES_REQUESTED: 1 blocker (guarda de nomes quebra no Python 3.12+ — f-strings não são lidas pelo tokenize, CI 3.15 vermelha) + 5 minor (padrões folder/backup com lacunas, output alcança poucos arquivos, old-config não segue link simbólico como as skills, arquivo não UTF-8 pulado) + 2 nits (exceções E6b/E6d largas; docs) | 2026-11-17 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-17 | G1 | spec | guarda de nomes acha usos reais fora do touches: gluon-spec SKILL.md:168 e references/brownfield.md:31 citam ~/.config/org-atlas como pasta do atlas; collector-contract.md:5 descreve o snapshot ao contrário; testes e fixtures com o nome antigo fora de tests/plugin | listar exceções estreitas; nenhuma cabe sem esconder referência errada | architect | Emenda v3 — touches inclui gluon-spec SKILL.md/brownfield.md, collector-contract.md e testes/fixtures; exceções estreitas confirmadas | 2026-11-17 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v2 | 2026-11-17 | `touches` ganha `mcp/tests/test_brain_server.py` e o plano ganha UT-04 (o teste do MCP passa a conferir também `~/.config/photon-brain`); a guarda de nomes aceita como exceção as docstrings "formerly org-atlas/second-brain" dos scripts e os fixtures de compatibilidade (`tests/fixtures/previous/`, `old-contract-name.json`, `legacy_contract.py`) | achados das revisões das SPEC-0069 e 0071 | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v3 | 2026-11-17 | `touches` ganha `skills/gluon-spec/SKILL.md` e `skills/gluon-spec/references/brownfield.md` (passam a citar `~/.config/boson-atlas`, com a antiga como reserva), `skills/boson-atlas/references/collector-contract.md` (a nota do snapshot diz o contrário do código: o `scan` grava o nome antigo até a SPEC-0073), os testes e fixtures da `boson-atlas`, `skills/photon-brain/tests/test_architecture.py` e `mcp/tests/helpers.py`, que deixam de usar o nome antigo fora dos fixtures de compatibilidade (coletores falsos e snapshots de fixture passam a `boson-atlas/collector@1`; testes que precisam do antigo o montam por partes); a guarda não confere comentários nem docstrings dos scripts, e nos Markdown isenta só notas de compatibilidade que trazem o nome novo correspondente | impedimento IMP-01: a guarda encontrou referências velhas reais, que uma exceção esconderia | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v4 | 2026-11-17 | Guarda de nomes: strings dos scripts lidas pela AST (f-strings incluídas, igual do Python 3.9 ao 3.15); `folder` acusa também depois de `/`; `backup` acusa `second-brain-` seguido de `<`, fim de string ou concatenação nos scripts; `output` cobre `skills/*/scripts/**/*.py`, `skills/*/assets/**/*.py`, `skills/*/assets/**/*.sh` e `tools/sdd/*.py`; arquivo de texto não UTF-8 é lido com substituição; E6b exige "compatib" ou "nome antigo" no título e E6d exige "antig" junto do nome novo correspondente. `old-config` do `fermion_doctor` acusa a pasta antiga mesmo quando é link simbólico (só confere existência, como as skills). README, `gluon-spec/SKILL.md` e `brownfield.md` dizem "quando o `config.yml` da pasta nova não existe", e a nota do README cita o prefixo novo dos backups | G4 da SPEC-0072 (CHANGES_REQUESTED): a guarda falhava no Python 3.15 da CI e deixava passar f-strings e outros casos | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v5 | 2026-11-17 | `touches` ganha `skills/boson-atlas/references/config.md` e `modes.md`: com as exceções E6b/E6d mais estreitas da v4, a seção "Atlas com a pasta antiga" passa a ter "nome antigo" no título e as duas linhas da tabela de mensagens do `doctor` citam também o nome novo | as notas de compatibilidade legítimas deixavam de ser isentas, e corrigi-las é mais estreito que alargar a exceção | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
