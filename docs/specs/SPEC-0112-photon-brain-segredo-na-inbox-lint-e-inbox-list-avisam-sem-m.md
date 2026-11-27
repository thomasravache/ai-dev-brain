---
id: SPEC-0112
title: "photon-brain: segredo na inbox — lint e inbox list avisam sem mostrar o valor"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-26
parent: SPEC-0093
depends_on: []
consumes_contract: []
contract_version: 4
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/references/confidential.md, skills/photon-brain/references/maintenance.md, skills/photon-brain/references/inbox.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_inbox_secrets.py, skills/photon-brain/tests/test_inbox_secrets_cli.py, .claude-plugin/plugin.json]
adrs: [ADR-0007, ADR-0014]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0112 — photon-brain: segredo na inbox — lint e inbox list avisam sem mostrar o valor

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O `lint` (`secret-in-note`) e o `inbox list` passam a pegar senha e token nos itens da inbox que hoje escapam — arquivos `.txt` e de link e rótulos como "Senha do wifi:" ou "PIN 1234" — e o `inbox list` mostra a prévia com o valor mascarado e um aviso, nunca o segredo (ponto 9 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** uma captura antiga da inbox tinha senhas em texto e o `lint --only secret-in-note` não acusou nada. O `lint` já lê as notas `.md` da inbox, mas não os itens `.txt`, `.url` e `.webloc`, e o detector só reconhece o rótulo seguido direto de `:` ou `=` ("senha: x"), não "Senha do wifi: x" nem "PIN 1234". O `inbox list` mostra até 120 caracteres do item, o que pode expor a senha.

**Objetivos (dentro do escopo):**
- `secret-in-note` cobre todos os itens de texto da inbox (`.md`, `.txt`) e os de link (`.url`, `.webloc`), além das notas de hoje; o achado cita o arquivo e a linha, nunca o valor (como hoje).
- O detector de rótulo aceita até três palavras entre o rótulo e o `:`/`=` ("senha do wifi:", "token da api =") e `PIN` seguido de 4 a 8 dígitos sem `:`.
- `inbox list` (texto e `--json`) marca o item com `possível segredo` e troca, na prévia, cada valor detectado por `•••`.
- `references/confidential.md`, `references/maintenance.md`, `references/inbox.md` e `SKILL.md`: ao processar um item com segredo, guardar no cofre e criar a referência (`--confidential`, SPEC-0050), nunca copiar o valor para uma nota.

**Não-objetivos (fora do escopo):**
- Apagar ou mover o item com segredo (só avisa; ADR-0015).
- Ler arquivos binários da inbox (PDF, imagem).
- Mudar a regra `personal-data`.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** o detector está em `SECRET_LABEL_RE`, `TOKEN_RE_SECRET`, `PRIVATE_KEY_RE` e `SECRET_PLACEHOLDER_RE` (`scripts/brain.py`), usado pelo `secret-in-note` de `LintVault` sobre `walk_vault` e `is_note`; o `inbox list` monta a prévia em `cmd_inbox_list` com a limpeza de caracteres de controle. Testes de referência: `SecretDetectorTest` (`tests/test_confidential.py`), `ConfidentialLintCliTest` (`tests/test_confidential_cli.py`) e `InboxListCliTest` (`tests/test_inbox_cli.py`).

**Decisão:** uma função `secret_spans(text)` que devolve as posições dos valores detectados (usada pelo `lint` e pela máscara da prévia); o `secret-in-note` passa a percorrer também os itens de texto e de link da inbox; a regex de rótulo ganha a forma com até três palavras e a do `PIN`.

**Justificativa:** um detector só para o `lint` e para a prévia evita que um ache o que o outro mostra (ADR-0014: o valor nunca aparece).

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** esconder a prévia inteira de todo item (perde a utilidade do `inbox list`); detector por entropia (falsos positivos demais em texto livre).

**ADRs:** ADR-0007, ADR-0014.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a inbox é lida uma vez por `lint`; itens maiores que 1 MiB são lidos só até 1 MiB.
- **Segurança:** nenhum valor detectado aparece na saída do `lint`, do `inbox list` (texto e JSON) nem no `log.md` — UT-04, UT-05.
- **Privacidade e dados pessoais:** mesma regra do valor; o achado cita só arquivo e linha.
- **Disponibilidade e resiliência:** item ilegível (codificação inválida) é pulado com um aviso, sem derrubar o `lint`.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A

## 6. Artefato A — Contrato
**Interface:** `lint --only secret-in-note`, `inbox list`

```text
rótulos detectados (sem diferença de caixa):
  <rótulo>[ até 3 palavras][*_]* [:=] <valor>     rótulo: senha|password|passwd|pwd|pin|token|api key|secret|segredo
  pin <4 a 8 dígitos>
  valores-marcador continuam ignorados (SECRET_PLACEHOLDER_RE); valor com menos de SECRET_MIN caracteres não conta
  tokens conhecidos e chave privada: como hoje

lint --only secret-in-note
  percorre: notas de hoje + inbox/*.md, inbox/*.txt, inbox/*.url, inbox/*.webloc
  achado: "AVISO secret-in-note <arquivo>:<linha> — parece senha ou token; guarde no cofre (references/confidential.md)"
  nunca o valor

inbox list [--json]
  item com segredo: "... <caminho> (possível segredo)" e a prévia com cada valor trocado por "•••"
  --json: "secret": true e "preview" já mascarada
  item sem segredo: como hoje
```

**Esclarecimentos (Emenda v2):**
- O achado do `secret-in-note` nos itens da inbox tem a severidade de hoje da regra (AVISO, exit 0), igual ao das notas; esta spec não muda a severidade.
- O nome da captura (`capture_name`, e por ele o `log.md` e as saídas do `capture`) nunca leva um valor detectado: o slug é montado das primeiras palavras do texto depois de tirar cada trecho de `secret_spans` (o rótulo fica: "Senha do wifi: abc12345" → `...-senha-do-wifi.md`). Texto só com segredo cai no nome padrão `captura` (UT-07).

**Esclarecimentos (Emenda v3):**
- **Nome antigo com o valor:** um item da inbox cujo nome contém o slug (`slugify`) de um valor detectado no conteúdo — capturas feitas antes desta versão — aparece no `lint` e no `inbox list` (texto e JSON) com esse trecho trocado por `•••` (ex.: `inbox/2026-01-01-120000-senha-do-wifi-•••.md`). Só trechos de 4 caracteres ou mais são trocados.
- O caminho mascarado é aceito como ITEM por `ingest` e `inbox done` quando identifica um único item da inbox; se não identificar, exit 2 com "item não encontrado" (sem o valor).
- Ao sair da inbox (`ingest --move`, `inbox done`), um item assim vai para o destino com o trecho trocado por `segredo`; o `log.md`, o título da nota de fonte e as saídas usam esse nome limpo, nunca o valor.
- **Palavras do rótulo:** as até 3 palavras entre o rótulo e o `:`/`=` são palavras de letras (`[^\W\d_][\w'-]*`): não cruzam `|`, `—`, parênteses, crase nem números.
- Diferenças aceitas e documentadas em `references/inbox.md`: o `inbox list` lê só os primeiros 8 KiB do item para a prévia e a marca, e o `lint` lê até 1 MiB; um valor com espaço entre aspas é mascarado só até o primeiro espaço.

**Esclarecimentos (Emenda v4):**
- O trecho trocado por `•••` (e por `segredo` no destino) é o slug do valor inteiro **ou** o maior prefixo dele, com 4 caracteres ou mais, que termina o nome (antes da extensão e de um `-N` opcional) — o nome antigo foi cortado em `SLUG_MAX` e pode ter só o começo do valor.
- O trecho só é trocado quando está entre limites do slug: começo do nome ou `-` antes, e `-`, `-N`, a extensão ou o fim depois. Dígitos da data e da hora do nome (`AAAA-MM-DD-HHMMSS`) nunca são trocados.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (regex de rótulo, `secret_spans`, `secret-in-note` na inbox, máscara e marca no `inbox list`); referências e `SKILL.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Rótulo com palavras | "Senha do wifi: abc12345", "token da api = sk..." | detectado | UT-01 |
| PIN | "PIN 1234", "pin: 482910" | detectado | UT-01 |
| Falso positivo | "senha: ***", "a senha é forte", "PIN 12" | não detectado | UT-02 |
| Inbox `.txt` e link | segredo em `inbox/x.txt` e `inbox/y.url` | `lint` acusa arquivo e linha | UT-03, IT-01 |
| Sem o valor | qualquer achado | valor ausente de `lint`, `inbox list` e `log.md` | UT-04 |
| Prévia mascarada | `inbox list` com item com segredo | marca `possível segredo` e `•••` no lugar do valor; JSON com `secret: true` | UT-05 |
| Instrução | `confidential.md`, `maintenance.md`, `inbox.md`, `SKILL.md` | item com segredo vai para o cofre com referência, nunca para a nota | UT-06 |
| Detector de hoje | casos do `SecretDetectorTest` | iguais | CH-01 |
| Nome da captura | `capture` de "Senha do wifi: abc12345" | nome, log e saídas sem o valor | UT-07, IT-01 |
| Nome antigo com o valor | `inbox/...-senha-do-wifi-<valor>.md` | `•••` no caminho do `lint` e do `inbox list`; o caminho mascarado é aceito por `ingest`/`inbox done`; destino, log e título com `segredo` | UT-08 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Os casos de hoje do `SecretDetectorTest` e do `ConfidentialLintCliTest` (detectados e não detectados) continuam com o mesmo resultado, e nota `confidential: true` continua fora do `secret-in-note` (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — `secret_spans` acha o valor em "Senha do wifi: abc12345", "- **Senha do banco:** x9y8z7w6", "token da api = sk-abcdefghijklmnopqrstu", "PIN 1234" e "pin: 482910", e as posições cobrem só o valor.
- **UT-02** — `secret_spans` não acha nada em "senha: ***", "senha: <a sua>", "a senha é forte", "PIN 12", "o token do evento foi bom" e num rótulo com quatro palavras antes do `:`; e, com palavras que cruzam pontuação, em "| token | prefixo conhecido: x", "(token sem permissão): sinal" e "token 2026 do: abcdefgh" (número entre as palavras).
- **UT-03** — Num vault com `inbox/2026-01-01-wifi.txt` ("Senha do wifi: abc12345"), `inbox/link.url` com `?token=abcdef123456` e uma nota `.md` da inbox com "PIN 4821", o `lint --only secret-in-note` acusa os três com arquivo e linha.
- **UT-04** — Nas saídas de `lint`, `lint --json`, `inbox list` e `inbox list --json` e no `log.md` depois deles, nenhum dos valores do UT-03 aparece.
- **UT-05** — O `inbox list` marca os três itens com `(possível segredo)`, a prévia mostra `•••` no lugar de cada valor, e o `--json` traz `"secret": true` com a prévia mascarada; um item sem segredo sai como hoje.
- **UT-06** — `references/confidential.md`, `references/maintenance.md`, `references/inbox.md` e `SKILL.md` dizem que um item da inbox com segredo vai para o cofre com a referência `--confidential` e que o valor nunca entra numa nota nem numa resposta.
- **UT-07** — `capture_name` de "Senha do wifi: abc12345" não contém `abc12345` e contém `senha-do-wifi`; de "PIN 4821" não contém `4821`; de um texto que é só um token cai em `captura`; e o `capture` pela CLI desse texto não mostra o valor no nome do arquivo, na saída nem no `log.md`.
- **UT-08** — Com `inbox/2026-01-01-120000-senha-do-wifi-qz9vold1.md` contendo "Senha do wifi: qz9vold1": `lint`, `lint --json`, `inbox list` e `inbox list --json` mostram `...-senha-do-wifi-•••.md` e nunca `qz9vold1`; `inbox done` e `ingest --move` aceitam o caminho mascarado; depois do `inbox done` o item fica em `raw/processed/AAAA-MM/...-senha-do-wifi-segredo.md` e depois do `ingest --move` na pasta de arquivos de hoje (SPEC-0021) com o mesmo nome limpo, e nem o `log.md`, nem a nota de fonte, nem as saídas contêm `qz9vold1`; um caminho mascarado que não identifica item sai com 2. Também: um item antigo com `token: <valor de 70 caracteres>` e o nome cortado em 60 caracteres não mostra nenhum pedaço de 4 ou mais caracteres do valor em `lint` e `inbox list`; e um item com "PIN 2026" e nome `2026-01-01-120000-pin-2026.md` mostra `2026-01-01-120000-pin-•••.md`, com a data intacta, e vai para o destino `...-pin-segredo.md`.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init`, quando uma captura com "Senha do wifi: abc12345" (no começo do texto) entra pela `capture` e outra por arquivo `.txt`, então `inbox list` marca as duas, o `lint` acusa as duas com AVISO (a severidade de hoje do `secret-in-note`) e sai com o exit de hoje, e nenhum valor aparece nas saídas.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — `user_facing: false`, sem jornada crítica declarada.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox`; valores falsos que parecem senha e token (nunca reais).

**Ambiente de execução:** local e CI.

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** N/A
- **Compatibilidade:** o `lint` pode passar a acusar itens antigos da inbox; é o objetivo. O exit do `lint` com achado é o de hoje.
- **Observabilidade:** os achados do `lint`.
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] O `lint` passa a olhar a inbox? — Já olha as notas `.md` da inbox; o que falta são os itens `.txt` e de link e os rótulos com palavras no meio, o que explica o falso negativo do feedback (Architect, 2026-11-26, conferido no código)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: CH-01, UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01 com a tag `SPEC-0112:<ID>`, falhando pelo motivo certo (CH passando)
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 74bf6ea (árvore suja) | 2026-11-27 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=51)) — c2e4c0b | 2026-11-27 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — e1f05d7 | 2026-11-27 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — e2b9fc3 | 2026-11-27 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED na terceira rodada (nome cortado e limites do slug resolvidos; minors cosméticos no radar) — 07c78e8 | 2026-11-27 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-27 — CHANGES_REQUESTED: captura antiga com o valor no nome (slug de 6 palavras de antes) vaza o valor pelo caminho no lint, no inbox list e, pelo ingest --move, no log.md e no título da nota — b7d6174
- G4 FAIL 2026-11-27 — CHANGES_REQUESTED: nome antigo com o slug cortado em SLUG_MAX ainda vaza o prefixo do valor longo (token/JWT); máscara não respeita os limites do slug e pega dígitos da data — b503cd3
- G4 PASS 2026-11-27 — depois de 2 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0112`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 4 | 2026-11-27 | Máscara do nome antigo cobre o prefixo do valor cortado em `SLUG_MAX` e respeita os limites do slug (data e hora intactas) (UT-08) | 2º G4 da SPEC-0112: valor longo vazava pelo nome cortado; máscara pegava dígitos da data | nenhuma | thomas, 2026-11-27 (piloto automático com o recomendado) |
| 3 | 2026-11-27 | Nome antigo com o valor mascarado no `lint`/`inbox list`, aceito mascarado e limpo ao sair da inbox (UT-08); palavras do rótulo só de letras (UT-02); diferenças de leitura documentadas | G4 da SPEC-0112: captura antiga vazava o valor pelo nome | nenhuma | thomas, 2026-11-27 (piloto automático com o recomendado) |
| 2 | 2026-11-27 | Achado com a severidade de hoje (AVISO); nome da captura sem os valores detectados (UT-07) | SPEC_DEFECT do G1: contrato dizia ERRO, contra a regra de hoje; o slug da captura expunha o segredo | nenhuma | thomas, 2026-11-27 (piloto automático com o recomendado) |
