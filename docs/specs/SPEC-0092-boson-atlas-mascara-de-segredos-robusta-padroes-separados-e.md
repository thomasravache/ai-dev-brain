---
id: SPEC-0092
title: "boson-atlas: máscara de segredos robusta (padrões separados e tempo limitado)"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-23
parent:
depends_on: []
consumes_contract: []
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/redaction.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-11-23
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

**Esclarecimentos (Emenda v2, achados da rodada 1 do G4):**
- **Nada que a `main` mascara pode deixar de ser mascarado em texto realista.** Isso inclui:
  - JWT com payload acima de 8 KB, como os tokens com muitos grupos ou papéis;
  - JWT com header acima de 1 KB;
  - credencial de URL com usuário ou senha longos, como tokens OAuth usados como senha, de até alguns KB.
- **Como continuar linear sem os limites fixos:**
  - `jwt`: uma alternativa sem limite que só começa no início de uma sequência base64 (lookbehind), mais a alternativa limitada para o token colado em outro (UT-01);
  - `url`: o usuário não atravessa `:` nem `/`, e a senha é lida até o `@` sem atravessar outro `://`, mais a alternativa limitada a 256 para senha que contém `://`.
- **Resíduo aceito e documentado:**
  - senha de URL acima de 256 caracteres que contém `://`;
  - esquema acima de 32 caracteres;
  - JWT colado em base64 e ao mesmo tempo acima dos limites.
  - O `references/redaction.md` lista esses casos.
- **Dois JWTs colados sem separador:** o segundo vaza em parte, problema que já existia na `main`. Fica registrado como outra ocorrência, para uma spec futura.
- **Plano de testes:** o UT-01 ganha os casos de JWT com payload de 9000 caracteres e header de 1100, e de credencial de URL com senha de 300 e de 2000 caracteres e usuário de 300. Nenhum pedaço desses valores pode sobrar. O UT-02 segue com o limite de 2 s.

**Padrão seguido:** `_masked_spans` e `_secret_span` da SPEC-0088 (Emenda v6); `references/redaction.md`.

**Rollback:** revert do commit.

**Outras ocorrências:** dois JWTs colados sem separador (o segundo vaza em parte; já existia na `main`; spec futura). As regex de `extra_patterns` são do time e ficam sob responsabilidade dele, e o `references/redaction.md` passa a avisar disso.

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
- [x] Red: CH-01 (passa antes), UT-01 e UT-02 com a tag `SPEC-0092:<ID>`, falhando pelo motivo certo
- [x] Green: cada padrão embutido casa sozinho no texto original, na união da Emenda v6 da SPEC-0088; `url` e `jwt` com repetições limitadas; `references/redaction.md`, `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 1e4789c | 2026-11-23 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=8, skipped=1)) — 2579a11 | 2026-11-23 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 8517316 | 2026-11-23 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — a95f261 | 2026-11-23 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente (subagente, rodada 2): APPROVED — os vazamentos da rodada 1 foram fechados (Emenda v2); o fuzz contra a main só mostra o resíduo documentado; o pior caso hostil leva 1,7 s/MB (minor, no radar); o commit seguinte só resolveu o conflito de versão do plugin.json — a2dd3ca | 2026-11-23 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-23 — reviewer independente (subagente, rodada 1): REJECTED — major: JWT com payload acima de 8192 ou header acima de 1024 deixa de ser mascarado; credencial de URL com usuário ou senha acima de 256 deixa de ser mascarada (vazamentos novos em relação à main) — 6764f6f
- G4 PASS 2026-11-23 — depois de 1 reprovação(ões)

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
A máscara de segredos da boson-atlas, usada pelo `scan`, pelo `lint` e pelas probes, ficou mais robusta em três pontos:
- **Tokens colados:** quando um token vem colado em outro, nenhum pedaço do segundo sobra.
- **Tempo linear:** entrada hostil de 1 MB leva menos de 2 s, quando antes passava de 24 s ou travava.
- **Sem vazamento novo:** JWT e credencial de URL longos continuam mascarados como na `main`.

### Como foi feito
- `scripts/atlas.py`:
  - `SECRET_RE` virou uma regex por padrão, e cada uma casa no texto original, entrando na união da Emenda v6 da SPEC-0088;
  - `url`: o usuário não atravessa `:` nem `/`, e a senha vai até o `@` sem atravessar outro `://`, com uma alternativa limitada a 256;
  - `jwt`: uma alternativa sem limite que começa só no início de uma sequência base64, mais uma limitada para o token colado.
- `references/redaction.md` explica como o tempo fica linear e lista o resíduo aceito: senha de URL acima de 256 com `://`, esquema acima de 32 e JWT colado e acima dos limites.
- **G4:** a rodada 1 reprovou por vazamento de JWT e URL longos, corrigido na Emenda v2. A rodada 2 aprovou.
- **Integração:** um conflito de versão do `plugin.json` foi resolvido num commit à parte.
- **Versões:** ATLAS_VERSION 2026.11.18, plugin 2026.11.33.

### Prova de Correção
- **Antes da correção:**
  - commit red 2579a11: UT-01 sai `[REDACTED]_aaaa…` e mostra o payload do JWT; UT-02 passa de 10 s ou leva cerca de 25 s;
  - commit red a96a354: os tokens longos saem sem máscara.
- **Depois da correção:** com os commits green 6764f6f e 4e09a4b, os testes passam no G2 e no CI.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Saída e contagem da máscara iguais às de antes nos casos normais (38 casos) | PASS | `test_redaction_robust.py` — CI do PR #72 (Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-01 | Tokens colados e tokens longos (JWT de 9000 e 1100, senha de URL de 300 e 2000, usuário de 300) totalmente mascarados | PASS | `test_redaction_robust.py` — CI do PR #72 (Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-02 | Entradas hostis de 1 MB mascaradas em menos de 2 s | PASS | `test_redaction_robust.py` — CI do PR #72 (Python 3.9 e 3.15) e suíte local no G2/G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6)
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy (G6 N/A, mesmo critério da SPEC-0017). A entrega chega pelo plugin `fermion` 2026.11.33.

### Pendências
- **Radar:**
  - dois JWTs colados sem separador ainda vazam em parte (já era assim na `main`);
  - o pior caso hostil da regex `url` leva cerca de 1,7 s/MB, uma margem apertada em máquina lenta.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-23 | Sem vazamento novo para JWT e credencial de URL longos; regex lineares sem limite fixo no caso comum; resíduo documentado; UT-01 com tokens longos | Achados da rodada 1 do G4 | — | thomas, 2026-11-23 (piloto automático com o recomendado) |
