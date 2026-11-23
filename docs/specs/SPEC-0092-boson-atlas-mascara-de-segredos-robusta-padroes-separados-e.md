---
id: SPEC-0092
title: "boson-atlas: máscara de segredos robusta (padrões separados e tempo limitado)"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-23
parent:
depends_on: []
consumes_contract: []
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/redaction.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0092 — boson-atlas: máscara de segredos robusta (padrões separados e tempo limitado)

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
A máscara de segredos da boson-atlas (`_redact_text`, usada pelo `scan`, pelo `lint` e pelas probes) tem dois defeitos que já existiam na `main`. Os dois foram achados no G4 da SPEC-0088, rodada 4:

- **Tokens colados vazam em parte:**
  - os padrões embutidos rodam como uma alternância só (`SECRET_RE`), que acha casamentos da esquerda para a direita e sem sobreposição;
  - quando dois tokens estão colados, o casamento do primeiro esconde o segundo;
  - exemplos: `xoxb-1234567890-ghp_<36 letras>` sai `[REDACTED]_aaaa…`, e `ghp_<30 letras>eyJ….eyJ….<assinatura>` deixa o payload e a assinatura do JWT à mostra.
- **Tempo quadrático em entrada hostil:**
  - as regex `url` e `jwt` levam tempo quadrático;
  - `"a://:"*200000` (1 MB) passa de 60 s, e `("eyJ"+"a"*8+".")*80000` leva cerca de 25 s;
  - a saída de um adaptador ou um arquivo varrido pode travar a `probe` ou o `scan`.

**Impacto:** pedaço de segredo na saída, em caso raro, e travamento com entrada maliciosa ou com defeito.

## 2. Causa Raiz
- `_masked_spans` em `skills/boson-atlas/scripts/atlas.py` tira os trechos de `SECRET_RE.finditer`. Na alternância, cada posição é consumida por um padrão só, ao contrário da regra da Emenda v6 da SPEC-0088: cada padrão casa no texto original.
- Os padrões `url` e `jwt` de `SECRET_PATTERNS` têm partes repetidas sem limite, que voltam atrás (backtracking) em cada posição de começo.

## 3. Mudança Proposta
- **Padrões separados:** cada padrão embutido casa sozinho no texto original, e os trechos entram na mesma união da Emenda v6. `_secret_span` continua valendo para o `url`.
- **Regex limitadas:** `url` e `jwt` são reescritas com repetições limitadas (tamanho máximo de usuário, senha e segmento) ou com lookahead, para o tempo ficar linear. A máscara de 1 MB de entrada hostil leva menos de 2 s.
- **Não muda:** o que cada padrão mascara em texto normal, a contagem de trechos e os goldens do `scan`, do `lint` e das probes.

**Padrão seguido:** `_masked_spans` e `_secret_span` da SPEC-0088 (Emenda v6); `references/redaction.md`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma conhecida. As regex de `extra_patterns` são do time e ficam sob responsabilidade dele, e o `references/redaction.md` passa a avisar disso.

## 4. Plano de Testes (TDD)
- **CH-01** — Dados os textos dos testes de máscara de hoje (`test_hardening.py`, `test_scan.py`, `test_probe.py`), quando a máscara roda, então a saída e a contagem ficam iguais às de antes da mudança.
- **UT-01** — Dados `xoxb-1234567890-ghp_` mais 36 letras, e `ghp_` mais 30 letras seguido de um JWT, quando a máscara roda, então nenhum pedaço do segundo token sobra (falha antes: sobra `_aaaa…` e o payload do JWT).
- **UT-02** — Dadas as entradas hostis de 1 MB (`"a://:"*200000` e `("eyJ"+"a"*8+".")*80000`), quando a máscara roda, então termina em menos de 2 s cada (falha antes: mais de 20 s).
- Integração/E2E: N/A — função pura; o caminho da `probe` e do `scan` já é coberto pelos testes da SPEC-0088.

## 5. Questões em Aberto
Nenhuma.

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
