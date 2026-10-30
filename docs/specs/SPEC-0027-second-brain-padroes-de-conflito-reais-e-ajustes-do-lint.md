---
id: SPEC-0027
title: "second-brain: ajustes do lint, da busca e da exportação"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0023, SPEC-0024, SPEC-0026]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/maintenance.md, skills/second-brain/references/providers.md, skills/second-brain/references/config.md, skills/second-brain/references/notebooklm.md, skills/second-brain/references/search.md, skills/second-brain/references/query-flow.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0027 — second-brain: ajustes do lint, da busca e da exportação

## 1. Problema
A revisão G4 da SPEC-0023 aprovou o `lint` e apontou seis pontos.

1. (Separado para a SPEC-0028, a pedido do usuário em 2026-10-30.) A conferência dos padrões de conflito com cópias reais de cada provedor.
2. Um padrão escrito pelo usuário com backtracking catastrófico, como `(?P<base>(a+)+)b\.md$`, trava o `lint` e o `doctor`. Como o `brain-config.yml` é sincronizado, trava todas as máquinas.
3. Os padrões genéricos diferenciam maiúsculas: `Plano Conflict.md` não é detectado.
4. O `SKILL.md` sugere `index` para resolver uma nota órfã, mas isso não adianta para uma nota sem contexto.
5. Um caminho fora da pasta `files` (`../../x`, `/etc/hosts`) aparece como "não existe na pasta files".
6. `--only ""` mostra a mensagem "regra desconhecida:  —", com o nome da regra vazio.

A revisão G4 da SPEC-0024 (exportação para o NotebookLM) aprovou e apontou mais quatro pontos:

7. Se a escrita falha no meio, os arquivos já gravados ficam em `--out`. A pasta fica não vazia e bloqueia uma nova tentativa, com a mensagem "já existe", que confunde.
8. Duas notas cujos títulos só diferem na normalização Unicode (NFC e NFD) geram o mesmo nome de arquivo no APFS, e a exportação falha com um pacote parcial.
9. `flatten_links` reescreve wikilinks dentro de código (`` `[[x]]` `` vira `` `x` ``), o que altera exemplos de código.
10. Só o MOC exportado é bloqueado. Um MOC de outro contexto serve de caminho, e `export-notebooklm index` exporta quase o vault inteiro.

A revisão G4 da SPEC-0026 (ajustes da busca) aprovou e apontou mais quatro pontos:

11. O `lint` ainda lê arquivos `.md` ocultos, que a varredura da busca já ignora.
12. A exclusão de `index.md` e `log.md` compara o caminho exato, então não funciona quando muda a caixa (`Index.md`) ou a forma Unicode.
13. Dentro de um bloco ```, uma linha como "```python" fecha o bloco, mas o CommonMark não aceita texto depois de uma cerca de fechamento.
14. Em `references/search.md` há uma linha longa fora da quebra do arquivo, e o `references/query-flow.md` não diz que o `context` não expande pelo `index.md` nem pelo `log.md`.

## 2. Causa Raiz
Em `skills/second-brain/scripts/brain.py`:
- `GENERIC_CONFLICT_PATTERNS` não tem `(?i)`;
- `compile_conflict_patterns` aceita qualquer regex, sem limite;
- a mensagem de `check_missing_file` não diferencia "fora da pasta files" de "não existe";
- a validação de `--only` não trata uma lista vazia.

O texto da sugestão de órfã está no `SKILL.md`.

## 3. Mudança Proposta
- O padrão genérico de "conflict" passa a ignorar maiúsculas.
- Padrões com quantificador aninhado (`(…+)+`, `(…*)*` e variações) são recusados com achado `config`. Cada padrão também tem limite de tamanho. `config.md` e `providers.md` avisam sobre isso.
- `missing-file` mostra o detalhe "fora da pasta files" quando é o caso, e `maintenance.md` diz isso.
- `--only` vazio sai com 2 e a mensagem "nenhuma regra em --only".
- O `SKILL.md` diz que o `index` só resolve órfãs que têm contexto; nas demais, usar `relate` ou uma nota nova.
- A exportação grava numa pasta temporária ao lado de `--out` e move tudo no final. Se falhar, nada fica em `--out`.
- Os nomes exportados são comparados com `unicodedata.normalize("NFC", …).casefold()`.
- `flatten_links` não mexe em código, nem em cercas nem em código inline.
- Na exportação, todos os MOCs (`layout.mocs`) ficam bloqueados como caminho, e `index.md` e `log.md` são recusados como MOC, com exit 2.
- O `lint` ignora `.md` ocultos como notas, com o mesmo filtro da varredura.
- `generated_paths` e as comparações de caminho de layout passam a usar `_link_key` (caixa e NFC).
- Uma cerca de fechamento só aceita espaços depois da marca.
- `search.md` tem a linha longa quebrada, e `query-flow.md` diz que o `context` não expande pelo `index.md` nem pelo `log.md`.

NÃO muda: as regras, as severidades, os formatos e os códigos de saída da SPEC-0023, nem o formato do pacote da SPEC-0024.

**Padrão seguido:** as funções `check_*`, `compile_conflict_patterns` e os testes `test_lint*.py` da SPEC-0023; `export_*`, `flatten_links` e `test_notebooklm*.py` da SPEC-0024.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0023 fixam o comportamento que não muda.
- **UT-01** — Dado o padrão `(?P<base>(a+)+)b\.md$`, quando `compile_conflict_patterns` roda, então ele é recusado como achado `config` sem tentar casar nenhum nome; e dado `Plano Conflict.md` ao lado de `Plano.md`, quando `check_conflict_copy` roda com os padrões genéricos, então a cópia é detectada.
- **UT-02** — Dado uma nota com `files: [../../x.pdf]`, quando `check_missing_file` roda, então o detalhe diz "fora da pasta files".
- **UT-03** — Dado o texto `` `[[codigo]]` e [[Nota]] ``, quando `flatten_links` roda, então devolve `` `[[codigo]]` e Nota ``; e dado dois títulos "Séries" em NFC e NFD, quando `export_name` roda, então gera nomes diferentes.
- **IT-02** — Dado uma falha simulada na escrita do terceiro arquivo, quando roda `export-notebooklm`, então `--out` continua vazio; e dado `export-notebooklm index`, então sai com 2; e dado uma nota citada que liga ao MOC de outro contexto, então as notas alcançadas só por esse MOC não entram.
- **UT-04** — Dado um bloco ``` com uma linha "```python" dentro e `#x` depois, quando `parse_note` roda, então `#x` não é tag; e dado `layout.index: index.md` com o arquivo `Index.md`, quando `generated_paths` é usado em `related`, então `Index.md` fica de fora.
- **IT-03** — Dado um vault com `.oculta.md` sem links, quando roda `lint`, então nenhum achado cita `.oculta.md`; e dado `references/query-flow.md`, quando lido, então diz que o `context` não expande pelo `index.md` nem pelo `log.md`.
- **IT-01** — Dado `--only ""`, quando roda `lint`, então sai com 2 e mostra "nenhuma regra em --only"; e dado um `brain-config.yml` com o padrão catastrófico e uma nota de 40 caracteres, quando roda `lint` e `doctor`, então os dois terminam em menos de 3 s com o achado `config`.

## 5. Questões em Aberto
- [x] A conferência com cópias reais de cada provedor fica aqui? — Não: vai para a SPEC-0028, separada, para esta spec seguir já (thomas, 2026-10-30)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 38e7d71 | 2026-10-30 |
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
