---
id: SPEC-0064
title: "photon-brain: título de nota confidencial fora do log.md na busca e no contexto"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-16
parent:
depends_on: []
consumes_contract: []
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/tests/**, skills/photon-brain/CHANGELOG.md, skills/photon-brain/references/**, .claude-plugin/plugin.json]
adrs: [ADR-0014]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-16
---

# SPEC-0064 — photon-brain: título de nota confidencial fora do log.md na busca e no contexto

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O título (caminho) de uma nota `confidential: true` aparece em `search` e `context` sem `--include-confidential`. `new-note --confidential` grava no `log.md` uma linha como `- 2026-11-16 10:44 new-note projects/college/Payments Secret Plan.md — note; confidencial`, e o `log.md` gerado pode ser resultado de `search` (com snippet) e de `context` (com o conteúdo inteiro). Reprodução (Test-writer da SPEC-0059, 2026-11-16): num vault criado pela CLI, `search --json -- zebracorn secret` devolve só o `log.md`, com o título no snippet; `context --json -- payments` traz o `log.md` com essa linha. O corpo não vaza. O ADR-0014 diz que nota confidencial fica fora da busca e do contexto por padrão; o título é dado sensível (nomes de projeto, pessoas, contratos) e também chega a qualquer cliente MCP pela SPEC-0059.

## 2. Causa Raiz
`search` e `build_context` (`skills/photon-brain/scripts/brain.py`) aplicam `visible_notes` às notas, mas o `log.md` gerado é uma nota comum para a busca: o texto dele entra inteiro na pontuação, no snippet e no pacote, inclusive as linhas que citam notas confidenciais. O `index.md` gerado já deixa as confidenciais de fora; o `log.md` não pode, porque é só acréscimo (ADR-0007) e as linhas antigas já existem nos vaults.

## 3. Mudança Proposta
- Sem `--include-confidential`, `search` e `context` leem o `log.md` gerado sem as linhas que citam uma nota confidencial (o caminho como o `log.md` o escreve, inclusive linhas antigas); pontuação, snippet e conteúdo do pacote usam esse texto, e o `log.md` só aparece se ainda casar com a consulta. Com `--include-confidential`, nada muda.
- O arquivo `log.md` não muda (só acréscimo, ADR-0007), e as linhas novas continuam registrando o caminho, para a pessoa auditar o vault.
- `references/` e CHANGELOG da `photon-brain`, `BRAIN_VERSION` e `version` do plugin sobem.
- **Não muda:** `related` e `links` (não usam o texto do `log.md`), o `index.md`, o `lint` e o `export-notebooklm`, que já tratam confidenciais.
**Padrão seguido:** `visible_notes` e `confidential_omitted` de `search`/`build_context`; `_link_key` para comparar o caminho como o `log.md` o escreve

**Rollback:** reverter o commit

**Outras ocorrências:** a linha `inbox-move` do `ingest --move` cita o arquivo original e o guardado (em `<files>/…`) sem o caminho da nota; entra nesta spec pela Emenda v2

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0064:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — `search` e `context` já têm suíte; com `--include-confidential` o resultado continua o mesmo (coberto no UT-01)
- **UT-01** — Dado um vault de teste com uma nota confidencial criada por `new-note --confidential` (título "Payments Secret Plan") e o `log.md` gerado, quando `search` e `context` rodam com uma consulta que casa com o título, então nenhum resultado, snippet ou conteúdo traz o título nem o caminho dela; com `--include-confidential`, o `log.md` volta a trazer a linha.
- **UT-02** — Dado um vault de teste com uma nota de fonte criada por `ingest --move --confidential` a partir de `inbox/Contrato Fulano Beltrano.pdf`, uma linha `relate … → [[Payments Secret Plan|apelido]]`, linhas antigas em MAIÚSCULAS, em NFD e com `\`, e uma nota comum `Business Plan.md` cujo caminho termina como o de uma confidencial `Plan.md`, quando `search` e `context` rodam, então nenhuma linha que cite a nota confidencial ou o arquivo guardado dela (nome original em `inbox/` ou caminho em `<files>/`) aparece, e as linhas da nota comum continuam encontráveis.
- **IT-01** — Dado o mesmo vault criado pela CLI real, quando `brain.py search --json` e `brain.py context --json` rodam como processo, então o stdout não contém o título nem o caminho da nota confidencial, e uma linha do `log.md` sobre uma nota comum continua encontrável.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 e IT-01 em `skills/photon-brain/tests/` com a tag `SPEC-0064:<ID>`, falhando pelo motivo certo
- [x] Green: `search` e `build_context` leem o `log.md` gerado sem as linhas de notas confidenciais
- [x] Validar: suíte completa + arquitetura (G2/G3); `references/`, CHANGELOG, `BRAIN_VERSION` e `version` do plugin
- [x] Review independente (G4), integração + CI (G5) e H2, Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — be69b32 | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=8)) — 4f9e9ee | 2026-11-16 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 20fc1fd | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 7789d5f | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 2, após Emenda v2: arquivo guardado e inbox-move escondidos, caminho ancorado sem falso positivo por sufixo, custo por linha em conjunto; 2 minors e 1 nit como pendências) — 8e2d233 | 2026-11-16 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — f0fcacd | 2026-11-16 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-16 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-16 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — e65c40d | 2026-11-16 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-16 | G2 | trabalho | TEST_DEFECT do Implementer: assertNothingHidden procura o título também no campo query, que só ecoa a consulta (que é o título); 6 subtestes falham com a saída limpa | Implementer provou com cópia do teste sem o campo query: UT-01 e IT-01 passam | Test-writer | SPEC-0064 — teste corrigido pelo Test-writer em 04cb1c3 (campo query fora da checagem de vazamento) | 2026-11-16 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- Sem `--include-confidential`, `search` e `context` da `photon-brain` (e as tools `brain_*` do MCP, que chamam a CLI) leem o `log.md` gerado sem as linhas que citam uma nota confidencial: pelo caminho dela, por um `[[link]]` que resolve para ela, pelo arquivo guardado de uma nota de fonte confidencial (em `<files>/…` e pelo nome original em `inbox/`), inclusive linhas antigas, em outra caixa ou em NFD. O arquivo `log.md` não muda. `BRAIN_VERSION` 2026.11.7; plugin 2026.11.11.

### Como foi feito
- `confidential_log_keys` junta num conjunto o que identifica as confidenciais; `log_paths` só lê caminhos onde o `log.md` os escreve (depois do comando, `→ `, `← `, `— `, `nota: `), sem falso positivo por sufixo e com custo por linha que não cresce com o número de confidenciais; `readable_notes` troca só a nota do `log.md` por uma versão filtrada em `search` e `build_context`.
- Testes em 4f9e9ee, 04cb1c3 (TEST_DEFECT do campo `query`, IMP-01) e f56e650; correção em 780af86 e 20fc1fd.
- **Emenda v2:** arquivo guardado e `inbox-move`, caminho ancorado, custo por linha e UT-02.
- **Revisão G4:** rodada 1 REJECTED (blocker: o nome do arquivo de `ingest --move --confidential` vazava pela linha `inbox-move`; major: testes sem `[[link]]`, NFC e caixa; minors: falso positivo por sufixo e custo); rodada 2 APPROVED.

### Prova de Correção
- **Antes:** 4f9e9ee vermelho (o snippet do `search` trazia "projects/college/Payments Secret Plan.md — note; confidencial" e o `context` trazia o `log.md` inteiro); f56e650 vermelho (a linha `inbox-move inbox/Contrato Fulano Beltrano.pdf → …` aparecia, e a linha de `Business Plan.md` sumia por causa da confidencial `Plan.md`).
- **Depois:** 20fc1fd verde; suíte completa em 3.9 e 3.14 e CI do PR #36.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `search` e `context` sem o título ou o caminho da confidencial pelo `log.md`; com `--include-confidential` a linha volta; arquivo no disco igual | PASS | `test_confidential_log.py::ConfidentialLogUnitTest` — CI do PR #36 (run 43925080798, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | Arquivo guardado (`ingest --move --confidential`), `[[link]]` com apelido, linhas antigas em MAIÚSCULAS, NFD e com `\`, sem falso positivo por sufixo | PASS | `test_confidential_log.py::ConfidentialLogAmendmentTest` — CI do PR #36 (run 43925080798, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | CLI real (`search --json`, `context --json`) sem o título; linha de nota comum encontrável | PASS | `test_confidential_log.py::ConfidentialLogCliTest` — CI do PR #36 (run 43925080798, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — 4f9e9ee/f56e650 vermelhos, 780af86/20fc1fd verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 2
- [x] Padrão existente mantido — `visible_notes` e `confidential_omitted`; ADR-0007 (log só acréscimo) e ADR-0014
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `references/confidential.md`, CHANGELOG `[2026.11.7]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — a linha `inbox-move` entrou pela Emenda v2; nenhuma outra

### Deploy
N/A — `BRAIN_VERSION` 2026.11.7, plugin 2026.11.11, PR #36.

### Pendências
Minors e nit da revisão, sem spec: o fecho de origens de move não tem teste (redundante no caso real); nenhum teste garante que só o `log.md` é redigido; linha escrita à mão fora do formato do log com o caminho no meio continua visível (fora do contrato).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-16 | Também ficam fora as linhas que citam o arquivo guardado de uma nota de fonte confidencial (`inbox-move` do `ingest --move`, pelo nome original e pelo caminho em `<files>/`); o caminho só casa com fronteira à esquerda (sem falso positivo por sufixo); a checagem por linha não cresce com o número de confidenciais (regex única ou conjunto); UT-02 novo | G4 rodada 1 (blocker: vazamento pelo `inbox-move`; major e minors da revisão) | nenhuma | thomas, 2026-11-16 (piloto automático com o recomendado) |
