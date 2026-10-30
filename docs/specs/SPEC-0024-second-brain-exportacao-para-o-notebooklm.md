---
id: SPEC-0024
title: "second-brain: exportação para o NotebookLM"
tier: lite
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0020]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/notebooklm.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0024 — second-brain: exportação para o NotebookLM

## 1. Problema
O NotebookLM é bom para estudar (resumos em áudio, perguntas guiadas), mas é um silo, e a v1 o usa só como saída opcional (SPEC-0016). Hoje, para levar as notas de uma disciplina até ele, seria preciso copiar nota por nota à mão, e as notas ligadas ficariam de fora.

## 2. Causa Raiz
Melhoria pequena. Não existe um comando que junte as notas de um MOC, e das notas ligadas a ele, num pacote pronto para subir no NotebookLM. A integração direta não é possível sem API pública oficial do NotebookLM de consumidor, e automação do navegador está fora do escopo (SPEC-0016).

## 3. Mudança Proposta
Comando `export-notebooklm MOC --out PASTA [--hops 0..2] [--combined]`:
- Junta o MOC e as notas que ele cita, mais os vizinhos até `--hops` (padrão 1), reusando a expansão do `context` (SPEC-0020).
- Grava fora do vault, em `--out`: um `.md` por nota com o título no topo, e um `sources.md` com a lista das notas e de onde veio cada uma.
- Com `--combined`, grava também um único `combined.md`, para quem quer usar poucas fontes.
- Os wikilinks viram texto simples (`[[Nota|apelido]]` → `apelido`) e os embeds de anexo viram `(anexo: nome)`.
- Nada no vault muda. `--out` dentro do vault, ou já com arquivos, sai com 2, porque o comando nunca sobrescreve.

Também entram o `references/notebooklm.md` (como subir o pacote, formatos aceitos e limites, conferidos na implementação com a data) e uma linha no `SKILL.md` dizendo quando oferecer a exportação ("me prepara para a prova" → oferecer o pacote do MOC).

NÃO muda: nenhum outro comando; nenhum acesso de rede; nenhuma escrita no vault.

**Padrão seguido:** `build_context` da SPEC-0020 para escolher as notas; `write_new_file` da SPEC-0019 para nunca sobrescrever; saída texto/`--json` dos demais comandos.

**Rollback:** `git revert` do merge.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — código novo; `build_context` é coberto pela SPEC-0020.
- **UT-01** — Dado o texto `Veja [[Regra do produto]], [[Integrais|integrais]] e ![[grafico.png]]`, quando `flatten_links` roda, então devolve `Veja Regra do produto, integrais e (anexo: grafico.png)`.
- **UT-02** — Dado o `SKILL.md` e `references/notebooklm.md`, quando lidos, então o `SKILL.md` diz quando oferecer a exportação, e o guia tem o passo a passo de envio e os formatos e limites com a data da conferência.
- **IT-01** — Dado um vault com o MOC `college` citando duas notas, uma delas ligada a uma terceira, quando roda `export-notebooklm college --out <temp> --combined`, então `<temp>` tem os quatro `.md` (MOC, as duas notas e a vizinha), o `sources.md` e o `combined.md`, sem wikilinks; o vault não muda; e, rodando de novo na mesma pasta ou com `--out` dentro do vault, o exit é 2.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01, UT-02 e IT-01 com a tag `SPEC-0024:<ID>`, falhando pelo motivo certo
- [ ] Green: `flatten_links` e `export-notebooklm`; `references/notebooklm.md` com formatos e limites conferidos (data); linha no `SKILL.md`
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=3)) — fbe3815 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — f42962d | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — f42962d | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (f42962d; 4 minor encaminhados para a SPEC-0027) — f42962d | 2026-10-30 |
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
