---
id: SPEC-0019
title: "second-brain: fluxo de guardar"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0018]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/store-flow.md, skills/second-brain/references/note-types.md, skills/second-brain/assets/templates/**, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008, ADR-0002]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0019 — second-brain: fluxo de guardar

## 1. Visão Geral
Implementa o fluxo padrão para guardar qualquer coisa no segundo cérebro: uma anotação, uma aula, um PDF, um vídeo ou um link. O `SKILL.md` define os seis passos que o agente sempre segue:
1. Classificar.
2. Guardar o bruto.
3. Buscar relações.
4. Escrever a nota sintetizada.
5. Atualizar índices e log.
6. Reportar.

O `brain.py` faz a parte determinística com os comandos `ingest`, `new-note`, `relate` e `index`, e registra tudo no `log.md`.

## 2. Motivação & Escopo
**Motivação:** sem um fluxo fixo, cada pedido gera notas em lugares e formatos diferentes, sem links, e o vault vira um depósito. O valor do segundo cérebro está em toda informação nova chegar ligada ao que já existe e encontrável pelos índices.

**Objetivos (dentro do escopo):**
- `ingest FONTE`, onde a fonte é um arquivo local ou uma URL:
  - arquivo: copia para a pasta de arquivos (`files`), sem sobrescrever;
  - em todos os casos, cria a nota de fonte em `raw/`, com o texto extraído quando houver (`--text-file`).
- `new-note`: cria a nota a partir do modelo do tipo, no lugar definido pelo contexto. Nunca sobrescreve.
- `relate DE PARA --why`: acrescenta a relação, com o motivo, na seção `## Relations` da nota, e com `--both` também na outra.
- `index`: regenera as regiões geradas dos MOCs dos contextos e do `index.md`, sem tocar no texto do usuário.
- Linha no `log.md` para toda escrita.
- Tipos de nota da v1, com modelo em `assets/templates/`: `note`, `lecture`, `source`, `video`, `document`, `link`, `moc`.
- No `SKILL.md`, o fluxo de guardar com os seis passos, as regras de síntese e o formato da seção `Relations`.

**Não-objetivos (fora do escopo):**
- Rodar processadores para extrair texto (SPEC-0022). Aqui o texto vem por `--text-file`, que o agente produz lendo o arquivo, ou fica vazio.
- Captura rápida e processamento da inbox (SPEC-0021).
- Baixar o conteúdo de URLs: a skill guarda o link. Ler a página fica com o agente, se ele tiver ferramenta para isso.
- Editar ou reescrever notas existentes além de acrescentar relações e das regiões geradas.

## 3. Dependências
- **Implementações necessárias:** SPEC-0018 — `scan_vault`, `parse_note`, `resolve_link` e `related`, usados no passo de relações e no `index`. Inclui, por transitividade, a configuração da SPEC-0017.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue a SPEC-0017 (`load_config`, regiões geradas `<!-- brain:begin/end -->`, linha no `log.md`) e a SPEC-0018 (`scan_vault`, `resolve_link`). A ideia das regiões geradas vem do `index` da `sdd-management`, que regenera o `INDEX.md` inteiro. Aqui a regeneração fica restrita a uma região, porque o MOC também tem texto do usuário.

**Decisão:** funções `write_new_file(path, text)`, que falha se o arquivo existir, `append_relation(note, target, why)` e `replace_region(text, name, content)`, que acrescenta a região no fim do arquivo quando ela não existe. Essas três são as únicas que escrevem no vault, e todas chamam `append_log`. O lugar da nota sai do contexto (`contexts.<c>.folder`); sem contexto, vai para `para.resources`.

**Justificativa:** concentrar a escrita em três funções garante a regra "só cria e acrescenta" do ADR-0007 e facilita o teste.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:**
- Deixar o agente escrever direto em qualquer arquivo, sem comandos: funciona, mas sem garantia de formato, de log e de não sobrescrever. O agente ainda escreve o *corpo* da nota direto no arquivo criado por `new-note`.
- Um banco de metadados ao lado do vault: duplicaria o que o frontmatter já guarda.

**ADRs:** ADR-0007, ADR-0008 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `index` em menos de 3 s num vault com 5.000 notas (IT-06).
- **Segurança:** nenhum comando sobrescreve ou apaga arquivo (UT-02, IT-05). Caminhos vindos de título ou contexto são normalizados, e um caminho que sairia do vault (`..`) é recusado com exit 2 (UT-01).
- **Privacidade e dados pessoais:** nada sai da máquina; os arquivos só são copiados para a pasta `files` configurada.
- **Disponibilidade e resiliência:** pasta `files` inacessível no `ingest` → exit 1 com a mensagem, e nenhuma nota de fonte criada pela metade (a cópia acontece antes da nota).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comandos `ingest`, `new-note`, `relate`, `index`; frontmatter e modelos dos tipos de nota; regiões geradas; linha de log; fluxo de guardar no `SKILL.md`.

```text
Frontmatter comum (chaves em inglês):
  type: note | lecture | source | video | document | link | moc
  title: <texto>
  context: <nome do contexto> | ausente
  created: AAAA-MM-DD
  tags: [..]
  source: "[[raw/<nota de fonte>]]" | <url> | ausente
  files: [<caminho relativo à pasta files>] | ausente
Corpo dos modelos: "# {title}", "## Summary", seções do tipo (lecture: "## Key points", "## Questions"; video:
  "## Timestamps"; document: "## Highlights"), "## Relations"

brain.py ingest FONTE [--context C] [--title T] [--text-file ARQ] [--json]
  FONTE arquivo: copia para <files>/<contexto ou "inbox">/<AAAA>/<nome>; nome existente → "<nome>-1", "-2"...
  FONTE URL (http/https): nada é copiado
  cria raw/AAAA-MM-DD-<slug>.md com type: source, title, created, context, source_url ou files, e o conteúdo de
    --text-file sob "## Extracted text" (ou "## Extracted text\n\n_(pending)_")
  json: {"raw": "<caminho no vault>", "file": "<caminho relativo a files>" | null, "url": ... | null}
  FONTE inexistente: exit 2 "fonte não encontrada: FONTE"; files inacessível: exit 1

brain.py new-note --type T --title X [--context C] [--source CAMINHO_OU_URL] [--tags a,b] [--json]
  caminho: <pasta do contexto ou para.resources>/<X sanitizado>.md (remove / \ : * ? " < > | # ^ [ ])
  conteúdo: modelo templates/<T>.md do vault (cai no modelo da skill se o do vault não existir), com
    os marcadores {title}, {date}, {context}, {source} preenchidos
  nota existente: exit 2 "nota já existe: CAMINHO" (nunca sobrescreve)
  tipo desconhecido ou contexto inexistente: exit 2 com a lista válida
  imprime o caminho (ou {"path":...} com --json)

brain.py relate DE PARA --why "motivo" [--both]
  acrescenta "- [[<nome de PARA>]] — <motivo>" no fim da seção "## Relations" de DE (cria a seção no fim se faltar)
  mesma relação já presente: nada muda, "relação já existe"
  --both: faz o mesmo em PARA apontando para DE
  DE ou PARA inexistente: exit 2

brain.py index [--context C]
  mocs/<contexto>.md: região "brain:begin notes" com as notas do contexto agrupadas por type, ordenadas por título,
    cada uma "- [[Título]]"; cria o MOC a partir do modelo moc se faltar
  index.md: região "brain:begin contexts" (cada contexto com link para o MOC e o total de notas) e
    região "brain:begin recent" (20 notas mais recentes pelo created)
  região ausente num arquivo existente: acrescentada no fim; texto fora das regiões nunca muda

log.md: uma linha por escrita, no fim do arquivo: "- AAAA-MM-DD HH:MM <comando> <caminho> [<detalhe>]"

SKILL.md — fluxo de guardar (sempre nesta ordem):
  1. Classificar: tipo (lista de note-types.md) e contexto (perguntar só se ambíguo; sugerir criar contexto novo)
  2. Guardar o bruto: arquivo ou link → ingest (texto extraído pelo agente em --text-file, quando ele consegue ler)
  3. Buscar relações: related --text com o conteúdo (e search pelos conceitos principais) antes de escrever
  4. Escrever: new-note e, em seguida, o corpo sintetizado no arquivo criado, no idioma do conteúdo; nunca alterar
     texto escrito pelo usuário em outras notas
  5. Ligar e indexar: relate para cada relação relevante, com o motivo (ex.: "aplica", "contradiz", "exemplo de",
     "pré-requisito de"); depois index do contexto
  6. Reportar: nota criada, relações e por quê, e insights (ligações novas ou lacunas)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Ingest de arquivo | PDF local com contexto | cópia em `files/<ctx>/<ano>/`, nota de fonte em `raw/`, log | IT-01 |
| Ingest de nome repetido | mesmo nome duas vezes | segunda cópia com `-1`; a primeira não muda | IT-01 |
| Ingest de URL | `https://…` | só a nota de fonte, com `source_url` | IT-01 |
| Ingest com texto | `--text-file` | texto sob `## Extracted text` | IT-01 |
| Fonte inexistente | caminho que não existe | exit 2 | IT-01 |
| files inacessível | pasta sem permissão | exit 1 e nenhuma nota de fonte | IT-05 |
| Nova nota | tipo e contexto válidos | arquivo do modelo na pasta do contexto | UT-01, IT-02 |
| Sem contexto | `new-note` sem `--context` | vai para `resources/` | UT-01 |
| Título com caracteres proibidos | `Aula 1: Limites/Derivadas` | nome sanitizado | UT-01 |
| Caminho fora do vault | contexto com `..` | exit 2 | UT-01 |
| Nota existente | mesmo título | exit 2, arquivo intacto | UT-02, IT-02 |
| Tipo ou contexto inválido | `--type foo` | exit 2 com a lista | IT-02 |
| Modelo do vault | `templates/lecture.md` alterado pelo usuário | `new-note` usa o do vault | IT-02 |
| Relação | `relate A B --why x` | linha na seção `Relations` de A | UT-03, IT-03 |
| Relação repetida | mesma relação | nada muda | UT-03 |
| Relação nos dois sentidos | `--both` | linha nas duas notas | IT-03 |
| Índices | `index` | regiões dos MOCs e do `index.md` regeneradas | UT-04, IT-04 |
| Texto do usuário no MOC | texto fora das regiões | intacto | UT-04, IT-04 |
| MOC sem região | MOC criado à mão | região acrescentada no fim | UT-04 |
| Log | toda escrita | uma linha por escrita | IT-05 |
| Fluxo completo | ingest → new-note → relate → index | nota ligada, MOC e log atualizados | IT-07 |
| Instruções | `SKILL.md`, `note-types.md` | seis passos na ordem e tipos da v1 | UT-05 |
| Desempenho | `index` com 5.000 notas | menos de 3 s | IT-06 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — código novo; as funções das SPEC-0017 e SPEC-0018 têm testes próprios.

### 7.2 Testes Unitários
- **UT-01** — Dado contextos `college → projects/college` e `bad → ../fora`, quando `note_path` recebe ("Aula 1: Limites/Derivadas", college), (título, sem contexto) e (título, bad), então devolve `projects/college/Aula 1 Limites Derivadas.md`, `resources/<título>.md` e um erro de caminho fora do vault.
- **UT-02** — Dado um arquivo existente, quando `write_new_file` é chamado no mesmo caminho, então lança o erro "nota já existe" e o conteúdo do arquivo não muda.
- **UT-03** — Dado uma nota sem `## Relations` e outra com a seção no meio do texto, quando `append_relation` acrescenta `[[B]] — aplica`, então a primeira ganha a seção no fim, a segunda ganha a linha no fim da seção (antes da próxima `##`) e repetir a chamada não muda nada.
- **UT-04** — Dado um MOC com texto antes e depois da região `notes` e outro sem região, quando `replace_region` roda com uma lista nova, então só o conteúdo entre os marcadores muda no primeiro e a região é acrescentada no fim do segundo.
- **UT-05** — Dado o `SKILL.md` e `references/note-types.md`, quando lidos, então o fluxo de guardar tem os seis passos na ordem do contrato, cita `ingest`, `related`, `new-note`, `relate` e `index`, e `note-types.md` descreve os sete tipos da v1, cada um com modelo em `assets/templates/`.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init` com o contexto `college` e uma pasta `files` temporária, quando roda `ingest aula.pdf --context college --text-file texto.txt`, depois `ingest aula.pdf --context college` de novo, `ingest https://example.com/x` e `ingest inexistente.pdf`, então a cópia está em `files/college/<ano>/aula.pdf`, a segunda é `aula-1.pdf`, as notas de fonte em `raw/` seguem o contrato (com o texto extraído na primeira), a URL gera só a nota de fonte e a fonte inexistente sai com 2.
- **IT-02** — Dado o mesmo vault, quando roda `new-note --type lecture --title "Integrais por partes" --context college`, repete o comando, roda com `--type foo` e, depois de alterar `templates/lecture.md` no vault, cria outra nota, então a primeira é criada do modelo, a repetição sai com 2 sem mudar o arquivo, o tipo inválido sai com 2 com a lista e a última usa o modelo alterado.
- **IT-03** — Dado duas notas, quando roda `relate A B --why "aplica"`, repete e roda `relate A C --why "contradiz" --both`, então A tem as duas relações uma vez cada, C tem a relação de volta e B não muda.
- **IT-04** — Dado notas em dois contextos e um MOC com texto escrito pelo usuário, quando roda `index`, então cada MOC lista as notas do contexto por tipo, o `index.md` lista os contextos com os totais e as 20 notas mais recentes, e o texto do usuário continua igual byte a byte.
- **IT-05** — Dado os comandos dos IT-01 a IT-04, quando o `log.md` é lido, então há uma linha por escrita no formato do contrato; e com a pasta `files` sem permissão de escrita, `ingest` sai com 1 e nenhuma nota de fonte é criada.
- **IT-06** — Dado um vault gerado com 5.000 notas em 5 contextos, quando roda `index`, então termina em menos de 3 s. É o teste do RNF de desempenho.
- **IT-07** — Dado um vault com a nota "Regra do produto" no contexto `college`, quando roda em sequência `ingest slides.pdf --context college --text-file slides.txt`, `related --text "<trecho de slides.txt>"`, `new-note --type lecture --title "Integrais por partes" --context college --source <raw>`, `relate "Integrais por partes" "Regra do produto" --why "aplica" --both` e `index --context college`, então "Regra do produto" aparece entre as relacionadas, as duas notas se citam com o motivo, o MOC de college lista a aula e o `log.md` tem as quatro escritas. É o critério de aceite "guardar" do épico.

### 7.4 Testes de Contrato
- N/A — sem contrato consumido; as SPEC-0020 a SPEC-0024 dependem da implementação.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração (IT-07 é a jornada completa de guardar). A parte do agente (síntese e escolha das relações) segue o `SKILL.md`, verificado no UT-05.

### 7.6 Outros
- Desempenho do `index`: IT-06.

**Dublês e dados de teste:** vaults e pastas `files` temporários criados pelo `init`; PDF sintético (bytes quaisquer com extensão .pdf, já que nada é extraído aqui); `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto (comandos novos).
- **Dados/schema:** frontmatter da v1 documentado em `note-types.md`; os modelos ficam no vault e o usuário pode alterá-los.
- **Compatibilidade:** N/A — primeira versão.
- **Observabilidade:** `log.md` com toda escrita.
- **Rollback:** `git revert` do merge. Notas já criadas continuam válidas, porque são Markdown comum.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Escrita segura**
- [x] Red: UT-01, UT-02, UT-03, UT-04 com a tag `SPEC-0019:<ID>`, falhando pelo motivo certo
- [x] Green: `note_path`, `write_new_file`, `append_relation`, `replace_region`, `append_log`
- [x] Refactor mantendo tudo verde

**Fase 2: Comandos de guardar**
- [x] Red: IT-01, IT-02, IT-03, IT-04, IT-05 com a tag `SPEC-0019:<ID>`, falhando pelo motivo certo
- [x] Green: `ingest`, `new-note`, `relate`, `index`; modelos dos 7 tipos
- [x] Refactor mantendo tudo verde

**Fase 3: Jornada, desempenho e instruções**
- [x] Red: IT-07, IT-06, UT-05 com a tag `SPEC-0019:<ID>`, falhando pelo motivo certo
- [x] Green: fluxo de guardar no `SKILL.md`, `store-flow.md`, `note-types.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [x] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=21)) — b7dbec2 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 9791639 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 9791639 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (9791639; 10 achados da 1ª rodada corrigidos; 2 minor opcionais) — 9791639 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 8988dc9 | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
O fluxo de guardar existe de ponta a ponta:
- `brain.py ingest` guarda o bruto: arquivo copiado para `files/<contexto>/<ano>/`, sem sobrescrever, ou link, e nota de fonte em `raw/`;
- `new-note` cria a nota a partir do modelo do tipo, na pasta do contexto;
- `relate --why` liga notas explicando o motivo, com `--both` para os dois lados;
- `index` regenera os MOCs e o `index.md` sem tocar no seu texto.

Toda escrita vai para o `log.md`. O `SKILL.md` traz os seis passos que o agente sempre segue: classificar, guardar o bruto, buscar relações, escrever, ligar e indexar, reportar.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `brain.py` (versão 2026.10.3) ganhou `note_path`, `write_new_file` (falha se a nota já existe), `append_relation`, `replace_region` e `append_log`. As escritas de `relate` e `index` são atômicas (arquivo temporário oculto + `os.replace`) e preservam BOM e CRLF.
- O `index` planeja e valida todos os arquivos antes de escrever qualquer um.
- Foram criados `references/store-flow.md` e `references/note-types.md`.
- A 1ª revisão G4 pediu mudanças: 1 blocker (marcadores desbalanceados num MOC apagavam texto do usuário), 1 major (nome de contexto editado à mão escapava do vault) e 8 minor. Os testes de regressão vieram antes da correção (red e198ade; fix f2b23f3 e 9791639), e a 2ª revisão aprovou.
- Desvios aceitos na revisão:
  - o nome de contexto é validado onde é usado, além do `doctor`;
  - o leitor de YAML trata `\"` e `''` dentro de aspas;
  - symlink dentro do vault é escrito no alvo, e fora do vault é recusado;
  - títulos são cortados em 200 bytes;
  - datas inválidas ficam fora de "recent".
- Ficaram 2 achados minor opcionais: o motivo da relação é comparado diferenciando maiúsculas, e um marcador citado num bloco de código faz o `index` recusar o MOC (falha segura).

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Caminho da nota pelo contexto, sanitizado, dentro do vault | PASS | `test_store.py::NotePathTest.test_context_folder_sanitized_title_resources_fallback_and_outside_vault; test_store.py::NotePathTest.test_every_forbidden_character_is_removed_from_the_file_name; test_store.py::NotePathTest.test_title_with_dots_never_leaves_the_folder; test_store.py::NotePathTest.test_unknown_context_lists_the_valid_ones` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| UT-02 | write_new_file nunca sobrescreve | PASS | `test_store.py::WriteNewFileTest.test_existing_file_raises_note_exists_and_is_not_touched` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| UT-03 | Relação acrescentada na seção Relations, sem duplicar (com apelido, CRLF) | PASS | `test_store.py::AppendRelationTest.test_section_created_at_the_end_when_missing; test_store.py::AppendRelationTest.test_line_goes_at_the_end_of_the_section_before_the_next_heading; test_store.py::AppendRelationTest.test_empty_section_of_the_template_gets_the_line; test_store.py::ReviewRegressionUnitTest.test_existing_relation_with_alias_is_not_repeated; test_store.py::ReviewRegressionUnitTest.test_crlf_text_keeps_crlf_line_endings` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| UT-04 | Região gerada substituída sem tocar no texto do usuário; marcadores desbalanceados recusados | PASS | `test_store.py::ReplaceRegionTest.test_only_the_content_between_the_markers_changes; test_store.py::ReplaceRegionTest.test_other_regions_are_untouched; test_store.py::ReplaceRegionTest.test_missing_region_is_appended_at_the_end; test_store.py::ReviewRegressionUnitTest.test_replace_region_refuses_unbalanced_or_duplicated_markers; test_store.py::ReviewRegressionUnitTest.test_replace_region_in_crlf_text_keeps_crlf_line_endings` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| UT-05 | SKILL.md com os seis passos e note-types.md com os sete tipos | PASS | `test_store_instructions.py::StoreFlowInstructionsTest.test_skill_md_has_the_six_store_steps_in_order_with_the_commands; test_store_instructions.py::StoreFlowInstructionsTest.test_note_types_reference_describes_the_seven_types_with_templates; test_store_instructions.py::StoreFlowInstructionsTest.test_store_flow_states_the_guaranteed_index_bound` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | ingest de arquivo e URL, nomes repetidos, texto extraído, nome de contexto inválido | PASS | `test_store_cli.py::IngestCliTest.test_ingest_copies_without_overwriting_creates_source_notes_and_rejects_missing; test_store_cli.py::ReviewRegressionCliTest.test_context_name_climbing_out_of_files_or_vault_is_refused` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-02 | new-note: modelo, nota existente, tipo inválido, modelo do vault, título com marcadores e título longo | PASS | `test_store_cli.py::NewNoteCliTest.test_new_note_from_template_never_overwrites_and_validates_type_and_context; test_store_cli.py::ReviewRegressionCliTest.test_title_with_markers_quotes_and_hash_is_kept_literally_and_readable; test_store_cli.py::ReviewRegressionCliTest.test_very_long_title_is_refused_or_truncated_without_errno` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-03 | relate, relação repetida, --both, CRLF e symlink | PASS | `test_store_cli.py::RelateCliTest.test_relate_appends_once_both_ways_and_rejects_missing_notes; test_store_cli.py::ReviewRegressionCliTest.test_relation_with_alias_counts_as_existing; test_store_cli.py::ReviewRegressionCliTest.test_relate_keeps_crlf_files_crlf; test_store_cli.py::ReviewRegressionCliTest.test_relate_never_replaces_a_symlinked_note_with_a_regular_file` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-04 | index de MOCs e index.md, texto do usuário intacto, marcadores quebrados, datas inválidas | PASS | `test_store_cli.py::IndexCliTest.test_index_regenerates_mocs_and_index_keeping_user_text; test_store_cli.py::ReviewRegressionCliTest.test_index_refuses_a_moc_with_unbalanced_or_duplicated_markers; test_store_cli.py::ReviewRegressionCliTest.test_index_never_writes_a_moc_outside_the_vault_for_a_hand_edited_context_name; test_store_cli.py::ReviewRegressionCliTest.test_index_keeps_crlf_files_crlf; test_store_cli.py::ReviewRegressionCliTest.test_invalid_created_date_never_goes_above_valid_recent_notes; test_store_cli.py::ReviewRegressionCliTest.test_index_never_replaces_a_symlinked_moc_with_a_regular_file` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-05 | Uma linha de log por escrita; files ou raw sem permissão | PASS | `test_store_cli.py::LogCliTest.test_every_write_adds_its_log_line; test_store_cli.py::LogCliTest.test_ingest_with_unwritable_files_folder_exits_1_and_creates_no_source_note; test_store_cli.py::ReviewRegressionCliTest.test_ingest_with_unwritable_raw_names_the_copied_file` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-06 | index com 5.000 notas abaixo de 3 s | PASS | `test_store_cli.py::IndexPerformanceCliTest.test_index_takes_under_3_seconds_on_5000_notes` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |
| IT-07 | Jornada completa de guardar | PASS | `test_store_cli.py::StoreJourneyCliTest.test_ingest_related_new_note_relate_both_and_index` — CI do PR #15 em 8988dc9 (run 41055883309, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — `index` em 0,35–0,56 s com 5.000 notas (meta: menos de 3 s), no IT-06; segurança pelo UT-01, UT-02, UT-04 e IT-01 a IT-05 (sem sobrescrever, sem sair do vault, sem apagar texto do usuário)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado; vale na `main` com o merge do PR #15
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: sem `living_docs` configurado
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.3. Rollback: revert do merge.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
Nenhuma nova. Os 2 minor opcionais da revisão (motivo da relação comparado sem ignorar maiúsculas e marcador citado em bloco de código) são aceitos como estão.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0019`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
