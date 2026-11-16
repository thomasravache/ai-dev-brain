---
id: SPEC-0068
title: "gluon-spec: hook do leak-check acha a ferramenta depois de update do plugin ou remoção da cópia"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-16
parent:
depends_on: []
consumes_contract: []
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/assets/hooks/pre-push-leak, skills/gluon-spec/tests/**, skills/gluon-spec/references/private-mode.md, skills/gluon-spec/CHANGELOG.md, tools/sdd/spec_graph.py, .claude-plugin/plugin.json, scripts/fermion_doctor.py, tests/plugin/**]
adrs: [ADR-0019]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-16
---

# SPEC-0068 — gluon-spec: hook do leak-check acha a ferramenta depois de update do plugin ou remoção da cópia

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Os repositórios em modo privado têm um `pre-push` do leak-check que grava o caminho absoluto da ferramenta no momento do `private init`. Nesta máquina (2026-11-16), 16 repositórios de trabalho gravaram `~/.claude/skills/sdd-management/scripts/spec_graph.py`, a cópia antiga com o nome velho. Ao apagar essa cópia (o passo recomendado para usar o plugin `fermion`), o hook antigo chama um arquivo que não existe e todo push é recusado com a mensagem enganosa "marcas do SDD encontradas"; o único escape é `--no-verify`, que pula a proteção. O hook atual (SPEC-0057) já procura a ferramenta, mas grava `Path(__file__)`: instalado pelo plugin, esse caminho fica na pasta versionada do cache do Claude Code e quebra a cada `claude plugin update`. E o `private init` não regrava um hook que já existe.

## 2. Causa Raiz
`install_leak_hook` (`skills/gluon-spec/scripts/spec_graph.py`) grava `str(Path(__file__).resolve())` em `__SDD_TOOL__`, e o template `assets/hooks/pre-push-leak` só tem esse caminho e o `tools/sdd/` não rastreado como opções; nenhum comando atualiza hooks já instalados.

## 3. Mudança Proposta
- O hook procura a ferramenta, na ordem: o caminho gravado (se existir); a `gluon-spec` do plugin `fermion` instalado, lida de `$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json` (senão `~/.claude/plugins/…`); as cópias de skill do usuário (`gluon-spec`, depois a antiga `sdd-management`); e o `tools/sdd/` não rastreado. Sem nenhuma, a mensagem diz que a ferramenta não foi encontrada (nunca "marcas do SDD encontradas").
- `private hooks --refresh` (no repositório atual; com `--scan PASTA`, em todo repositório git sob a pasta cujo remoto ou caminho está no registro como privado) regrava só os hooks que o próprio SDD instalou (reconhecidos pelo cabeçalho), nunca um hook de outra origem, mostrando o que mudou.
- O `fermion_doctor` (SPEC-0061) e o `private status` acusam hook do leak-check que aponta para ferramenta inexistente, com o comando de atualização (só avisa, ADR-0019).
- **Não muda:** o que o leak-check procura, o escape `--no-verify` do git, hooks de gerenciadores do time (`core.hooksPath`, husky, lefthook).
**Padrão seguido:** busca da ferramenta do template atual (SPEC-0057); leitura só de arquivos e aviso com comando do `fermion_doctor` (SPEC-0061, ADR-0019)

**Rollback:** reverter o commit; hooks regravados continuam funcionando com a ferramenta gravada

**Outras ocorrências:** os hooks `commit-msg` e `pre-commit` do `vendor --hooks` usam `tools/sdd/` versionado e não dependem do caminho da skill — a conferir na revisão

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0068:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- **CH-01** — Dado um repositório temporário em modo privado com o hook instalado pela versão atual, quando o push tem marca do SDD, então o hook recusa como hoje (comportamento preservado).
- **UT-01** — Dados um hook com caminho gravado inexistente e, em pastas temporárias, um `installed_plugins.json` apontando para uma cópia do plugin, quando o hook roda, então usa a `gluon-spec` do plugin; sem plugin e com só a cópia de skill do usuário, usa a cópia; sem nenhuma, a mensagem diz "ferramenta do leak-check não encontrada" e não "marcas do SDD encontradas".
- **UT-02** — Dados um hook antigo instalado pelo SDD (cabeçalho reconhecido) e um hook `pre-push` de outra origem, quando `private hooks --refresh` roda, então só o do SDD é regravado com o template atual e o outro fica igual.
- **IT-01** — Dado um repositório real em modo privado com o hook antigo que aponta para uma cópia apagada, quando `private hooks --refresh` roda e depois `git push` para um remoto local com uma marca do SDD, então o push é recusado pelo leak-check (e sem marca, aceito).

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Fase 1 (test-writer): CH-01, UT-01, UT-02, IT-01 em `skills/gluon-spec/tests/test_private_mode.py` e o aviso do doctor em `tests/plugin/test_fermion_doctor.py`, com `CLAUDE_CONFIG_DIR`/`HOME` temporários — commit `test(...)` vermelho
- [ ] Fase 2 (implementer): busca no template `pre-push-leak`, `private hooks --refresh [--scan]`, aviso em `private status` e check `broken-leak-hook` no `fermion_doctor`; `tools/sdd/` vendorizado, CHANGELOG, `references/private-mode.md`, versão do plugin
- [ ] Fase 3 (reviewer): G4 independente
- [ ] Depois do merge: `private hooks --refresh --scan ~/dev/repos` nesta máquina (com o ok do thomas)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c0ee531 | 2026-11-16 |
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
| v2 | 2026-11-16 | `touches` ganha `scripts/fermion_doctor.py` e `tests/plugin/**`; o refresh vira `private hooks --refresh` no repositório atual ou `--scan PASTA`, no lugar de "todos os repositórios do registro" | o aviso do doctor mora fora da skill; o registro guarda o remoto normalizado, não a pasta, então só uma varredura acha os repositórios | nenhuma | thomas, 2026-11-16 (piloto automático com o recomendado) |
