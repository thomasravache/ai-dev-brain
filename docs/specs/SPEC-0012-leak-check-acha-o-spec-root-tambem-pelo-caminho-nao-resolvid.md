---
id: SPEC-0012
title: leak-check acha o spec_root também pelo caminho não resolvido
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-10-26
parent:
depends_on: [SPEC-0011]
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, CHANGELOG.md]
adrs: [ADR-0006]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-26
---

# SPEC-0012 — leak-check acha o spec_root também pelo caminho não resolvido

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Na suíte rodada num Mac, 3 testes de `test_private_mode.py` falham desde a SPEC-0003; a CI (Linux) não vê. Dois são defeito de teste: comparam o `spec_root` gravado no registro com o caminho temporário não resolvido (`/var/folders/…`), mas o `private init` grava o caminho resolvido (`/private/var/folders/…`), de propósito (SPEC-0008 compara caminhos resolvidos). O terceiro mostra um defeito real: um arquivo que cita o `spec_root` pela forma não resolvida (`/var/…`) **não** é achado pelo `leak-check`, que só procura a forma resolvida e a forma `~/` relativa ao `HOME` como está. O mesmo vale para qualquer link simbólico no caminho, como um `HOME` que é link (comum em máquinas gerenciadas): o caminho vaza e o `leak-check` passa.

## 2. Causa Raiz
`build_leak_patterns` (`spec_graph.py:773`) monta o padrão do caminho com `str(Path(spec_root))` — já resolvido no registro (`cmd_private`, `:741`) — e o `~/` com `relative_to(Path.home())`, que falha quando o `HOME` é link (o resolvido não fica "dentro" do `HOME` literal). Nenhuma forma alternativa que aponte para a mesma pasta é considerada.

## 3. Mudança Proposta
`build_leak_patterns` passa a procurar todas as formas conhecidas do mesmo `spec_root`: a resolvida (como hoje); a forma sob `Path.home()` e `~/` tanto para o `HOME` literal quanto para o resolvido; e, quando o caminho resolvido começa com `/private/` e o mesmo caminho sem esse prefixo resolve para a mesma pasta, essa forma também (macOS: `/var`, `/tmp`, `/etc`). Formas repetidas viram um padrão só. Os dois testes com defeito passam a comparar com o caminho resolvido.

Não muda: o registro (continua gravando o caminho resolvido), a recusa de `spec_root` dentro do repositório (SPEC-0008), os demais padrões do `leak-check`, a saída dos achados.

**Padrão seguido:** padrões de caminho já existentes em `build_leak_patterns` (absoluto e `~/`) e os testes de `LeakCheckCommandTest`/`LeakFindingsTest` em `test_private_mode.py`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — o `spec_root` só entra em padrões pelo `build_leak_patterns`; os outros usos comparam caminhos resolvidos dos dois lados.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `LeakFindingsTest` já fixa as formas absoluta e `~/`; continuam passando.
- **UT-01** — Dado `HOME` apontando para um link simbólico `<tmp>/homelink` → `<tmp>/realhome` e um `spec_root` resolvido em `<tmp>/realhome/sdd/org/repo`, quando `leak_findings` roda sobre linhas que citam `<tmp>/homelink/sdd/org/repo/specs` e `~/sdd/org/repo`, então as duas linhas são achadas como "caminho do spec_root" (portável: roda em Linux e macOS).
- **IT-01** — Dado o modo privado com o `spec_root` sob um `HOME` que é link simbólico, quando um arquivo staged cita o `spec_root` pela forma do link e roda `leak-check --staged`, então sai com 1 e aponta o arquivo e a linha.
- **UT-02** — Dado os testes `test_project_exposes_the_mode_api` e `test_init_registers_and_creates_versioned_spec_root`, quando comparam o `spec_root`, então usam o caminho resolvido do lado esperado e passam no macOS e no Linux (correção de teste; a suíte inteira passa num Mac).

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
- [x] Gravar no registro também o caminho como digitado, em vez de derivar as formas? — Não: mudaria o registro (contrato da SPEC-0003); derivar as formas a partir do caminho resolvido cobre o `HOME` com link e o `/private` do macOS sem mudar contrato (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)
- [x] Depende da SPEC-0011? — Só para a ordem dos merges: a branch parte da `sdd/SPEC-0011` (IDs e `SDD_TOOL_VERSION` em sequência, 2026.10.10); o código não depende dela (Architect, 2026-10-26)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [ ] Red: UT-01 e IT-01 com a tag `SPEC-0012:<ID>`, falhando pelo motivo certo; UT-02 corrige os dois testes com defeito
- [ ] Green: formas alternativas do caminho em `build_leak_patterns`, seguindo o padrão citado
- [ ] Validar: suíte completa (agora verde também no macOS) + lint + arquitetura (G2/G3)
- [ ] `SDD_TOOL_VERSION` 2026.10.10 e CHANGELOG (ADR-0005)
- [ ] Review (G4), integração (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 06977fd | 2026-10-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=3, skipped=1)) — 0de32ae | 2026-10-26 |
| G2 Green | PASS | MANUAL: CI do GitHub no PR #7 em c7aed26 (run 40372988204): ruff check 'All checks passed!' e 140 testes OK em Python 3.9 e 3.15; local (macOS): 140 testes OK — só o lint não roda aqui (sem uv/ruff) | 2026-10-26 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — c267ff9 | 2026-10-26 |
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
