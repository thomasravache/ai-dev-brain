---
id: SPEC-0073
title: Remoção dos nomes técnicos antigos na versão anunciada
tier: lite
type: refactor
user_facing: false
status: approved
created: 2026-11-16
parent: SPEC-0067
depends_on: [SPEC-0069, SPEC-0070, SPEC-0071, SPEC-0072]
consumes_contract: []
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/tests/**, skills/photon-brain/references/**, skills/photon-brain/CHANGELOG.md, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/**, skills/boson-atlas/CHANGELOG.md, scripts/fermion_doctor.py, tests/plugin/**, README.md, .claude-plugin/plugin.json]
adrs: [ADR-0020]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0073 — Remoção dos nomes técnicos antigos na versão anunciada

## 1. Problema
As SPEC-0069 a 0071 deixam a leitura dos nomes antigos como reserva por três versões mensais (resposta do thomas na SPEC-0067). Passado esse prazo, o código ainda carrega a leitura dupla: `~/.config/second-brain`, `~/.config/org-atlas`, `.org-atlas/skill`, o contrato `org-atlas/collector@1` e o prefixo `second-brain-` dos backups. Dois caminhos para a mesma coisa custam manutenção e confundem o suporte.

**Quando:** não antes da terceira versão mensal depois da entrega das SPEC-0069 a 0071, na data anunciada nos CHANGELOGs da `photon-brain` e da `boson-atlas`. Antes disso esta spec fica aprovada, mas sem execução (`next` só a libera depois das dependências, e o despacho espera a data).

## 2. Causa Raiz
Compatibilidade temporária do ADR-0020 (leitura dupla com remoção anunciada); o prazo vence.

## 3. Mudança Proposta
- `photon-brain`: a leitura da configuração deixa de cair em `~/.config/second-brain`. Com só a pasta antiga, o comando responde "não configurado" e mostra o comando de cópia; a rotação e o `restore` continuam aceitando backups `second-brain-…zip` (são arquivos da pessoa, sem custo de manter).
- `boson-atlas`: a configuração deixa de cair em `~/.config/org-atlas` (mesma mensagem com o comando de cópia); `org-atlas/collector@1` deixa de ser aceito em saídas novas de coletor, o `scan` passa a gravar os snapshots com `boson-atlas/collector@1` (até aqui grava o nome antigo, SPEC-0071 Emenda v3), e snapshots antigos continuam lidos pelo `build`; `.org-atlas/skill` continua tratada como ferramenta (nunca como conteúdo) e o `vendor` passa a sempre gravar `.boson-atlas/skill`, avisando que a CI personalizada precisa migrar.
- Ao passar a gravar snapshots com o nome novo, o CHANGELOG anuncia a versão mínima da `boson-atlas` (2026.11.8) para máquinas que compartilham o atlas, porque versões anteriores ignorariam esses snapshots no `build`; e os fixtures de comportamento que ainda emitem o nome antigo (`fake-collectors/*`, `curate/signals.py`, `build/replay.py`, snapshots de `lint/atlas/`) migram para o nome novo, ficando só os de compatibilidade nomeados como tal (achados da revisão da SPEC-0071).
- `fermion_doctor` e a guarda de nomes: as exceções de compatibilidade saem; os avisos de migração ficam por mais um ciclo.
- README e CHANGELOGs: registro da remoção.
- **Não muda:** nada é apagado na máquina ou no atlas da pessoa (ADR-0019); backups antigos continuam restauráveis.

**Padrão seguido:** remoção anunciada do ADR-0020; mensagens de "não configurado" e de comando sugerido das SPEC-0069 e 0070

**Rollback:** reverter o commit; a leitura dupla volta

**Outras ocorrências:** nenhuma — o `sdd-management` não tem nome técnico na `gluon-spec`

## 4. Plano de Testes (TDD)
- **UT-01** — Dada uma máquina simulada com só `~/.config/second-brain` (e outra com só `~/.config/org-atlas`), quando um comando que precisa de configuração roda, então sai "não configurado" com o comando de cópia, sem ler a pasta antiga.
- **UT-02** — Dada uma saída de coletor com `org-atlas/collector@1`, quando validada, então há a violação "contract não suportado" com a dica do nome novo; quando o `scan` grava uma saída válida, então o snapshot traz `boson-atlas/collector@1`; e dado um atlas com snapshots antigos, quando `build` roda, então funciona.
- **UT-03** — Dado um destino com backups `second-brain-…zip`, quando a rotação e o `restore` rodam, então continuam funcionando.
- **UT-04** — Dado um atlas com CI personalizada que roda `.org-atlas/skill`, quando `vendor` roda, então grava só `.boson-atlas/skill` e avisa que a CI precisa migrar.
- **UT-05** — Quando a guarda de nomes roda nos arquivos versionados reais, então nenhuma exceção de compatibilidade de leitura é mais necessária.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 (árvore suja) | 2026-11-16 |
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
| IMP-01 | 2026-11-17 | — | externo | remoção anunciada: não antes de 2027-03 (três versões mensais depois das SPEC-0069 a 0071, CHANGELOGs da photon-brain 2026.11.8 e da boson-atlas 2026.11.7/2026.11.8) | — | thomas (data) |  |  |

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
