---
id: SPEC-0064
title: "photon-brain: título de nota confidencial fora do log.md na busca e no contexto"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-16
parent:
depends_on: []
consumes_contract: []
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/tests/**, skills/photon-brain/CHANGELOG.md, skills/photon-brain/references/**, .claude-plugin/plugin.json]
adrs: [ADR-0014]
external: []
size: S
approved_by:
approved_at:
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

**Outras ocorrências:** Nenhuma conhecida — a revisão confere `capture`, `ingest` e `inbox done`, que também escrevem no `log.md`

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0064:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — `search` e `context` já têm suíte; com `--include-confidential` o resultado continua o mesmo (coberto no UT-01)
- **UT-01** — Dado um vault de teste com uma nota confidencial criada por `new-note --confidential` (título "Payments Secret Plan") e o `log.md` gerado, quando `search` e `context` rodam com uma consulta que casa com o título, então nenhum resultado, snippet ou conteúdo traz o título nem o caminho dela; com `--include-confidential`, o `log.md` volta a trazer a linha.
- **IT-01** — Dado o mesmo vault criado pela CLI real, quando `brain.py search --json` e `brain.py context --json` rodam como processo, então o stdout não contém o título nem o caminho da nota confidencial, e uma linha do `log.md` sobre uma nota comum continua encontrável.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
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

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

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
