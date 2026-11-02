---
id: SPEC-0050
title: "second-brain: itens confidenciais e cofre de senhas"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-02
parent:
depends_on: [SPEC-0023, SPEC-0024, SPEC-0044]
consumes_contract: []
contract_version: 2
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/confidential.md, skills/second-brain/references/maintenance.md, skills/second-brain/references/note-types.md, skills/second-brain/references/config.md, skills/second-brain/assets/templates/secret-ref.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0013, ADR-0014]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-02
---

# SPEC-0050 — second-brain: itens confidenciais e cofre de senhas

## 1. Visão Geral
O segundo cérebro passa a conviver com informação confidencial sem expô-la. **O segredo nunca entra no vault nem passa pela LLM.** São quatro peças, todas agnósticas de gerenciador de senhas, de provedor e de agente:
- **Referência ao cofre:** uma nota `secret-ref` diz que um segredo existe e onde ele está (`vault_ref: "keepass://Pessoal/Banco"`), sem conter o segredo. A skill nunca abre o cofre: quem abre é a pessoa.
- **Documento confidencial opaco:** `ingest --confidential` guarda o arquivo (RG escaneado, contrato, comprovante) em `files/` sem rodar processador e sem extrair texto. A nota de fonte só registra o nome, o tamanho e o hash.
- **Fora de vista por padrão:** notas com `confidential: true` ficam fora da busca, do `context`, do `related`, dos `links`, dos MOCs e do `index.md`, a menos que a pessoa peça (`--include-confidential`). Da exportação para o NotebookLM elas ficam sempre fora.
- **Alarme de vazamento:** duas regras novas do `lint`, só AVISO e sem mostrar o valor, apontam segredo (`secret-in-note`) ou dado pessoal (`personal-data`) escrito numa nota que não é confidencial.

## 2. Motivação & Escopo
**Motivação:** a pessoa quer o segundo cérebro como lugar central também para o que é sensível. Hoje ela usa o KeePass para as senhas e tem documentos com dados dela mesma. A skill não pode virar um vazamento: o vault sincroniza com a nuvem, a LLM lê o que a busca devolve, e existem a exportação e o conector.

**Objetivos:**
- Tipo de nota `secret-ref` e chave de frontmatter `confidential: true` (qualquer tipo de nota pode ser confidencial).
- `new-note --type secret-ref --vault-ref REF` e `new-note --confidential`.
- `ingest --confidential` para arquivo, sem extração.
- Filtro padrão em `search`, `related`, `context`, `links` e `index`, com `--include-confidential`; a exportação para o NotebookLM nunca inclui item confidencial; as saídas `--json` contam quantos foram omitidos (`confidential_omitted`), sem citar nenhum.
- `lint`: `secret-in-note` e `personal-data` (AVISO), com detectores configuráveis.
- `doctor`: quantas notas confidenciais existem (só o número).
- `SKILL.md` e `references/confidential.md`: as regras para o agente, inclusive no modo só conector (SPEC-0044).

**Não-objetivos:**
- A skill ler, escrever, gerar ou mostrar senhas, ou abrir o arquivo do gerenciador (`.kdbx` e outros).
- Criptografia própria no `brain.py` (só biblioteca padrão, e cripto caseira é risco).
- Integração com a API ou a CLI de qualquer gerenciador de senhas.
- Tirar dados pessoais de notas que já existem: o `lint` aponta, e a correção é da pessoa.

## 3. Dependências
- **Implementações necessárias:** SPEC-0023 (`lint`), SPEC-0024 (exportação) e SPEC-0044 (modo só conector), já implementadas, que ganham o filtro.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** nenhum. Um gerenciador de senhas da pessoa é opcional.

## 4. Decisão Arquitetural
**Contexto:** projeto existente; segue o ADR-0007 (só biblioteca padrão, sem rede, só cria e acrescenta) e o ADR-0013 (o conector só cria arquivo novo na inbox e só lê).

**Decisão (ADR-0014):** o segredo fica sempre fora do vault, no gerenciador da pessoa, e o vault guarda só a referência. Itens confidenciais são opacos (nunca extraídos) e ficam fora de vista por padrão em todo comando que mostra notas. A referência é um texto livre no formato `<esquema>://<caminho>`, que a skill só valida e nunca abre.

**Referência de implementação:**
- regras do `lint`: `LINT_CHECKS` e `LINT_SEVERITY` (SPEC-0023);
- padrões vindos da configuração com proteção contra regex que trava: `compile_conflict_patterns` (SPEC-0023);
- `ingest` e a nota de fonte: `cmd_ingest` e `render_source_note` (SPEC-0019);
- tipos de nota: `NOTE_TYPES` e `assets/templates/` (SPEC-0019).

**Justificativa:** manter o segredo fora do vault é o único jeito de ser agnóstico e seguro ao mesmo tempo. Qualquer gerenciador funciona, nenhuma senha sincroniza pela pasta, e a LLM nunca vê o valor.

**Desvio do padrão existente:** nenhum. Os filtros são novos, e o comportamento das notas não confidenciais não muda.

**Alternativas descartadas:** guardar senhas cifradas no vault com cripto própria; integrar com a API ou a CLI do KeePass ou de outro gerenciador (deixa de ser agnóstico e põe o segredo ao alcance do agente); manter os itens confidenciais numa pasta separada (não protege uma nota confidencial que a pessoa deixou em outra pasta, e a marca no frontmatter vale em qualquer lugar).

**ADRs:** ADR-0007 e ADR-0013 (aplicados); ADR-0014 (novo).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** as duas regras novas leem as notas na mesma passada do `lint`. Sem teste de tempo novo (os de tempo já existentes cobrem a busca).
- **Segurança:** nenhum valor de segredo ou de dado pessoal aparece na saída do `lint`, do `doctor` ou do `log.md` (UT-05, IT-06). Um documento confidencial nunca passa por processador (IT-03). Os padrões vindos da configuração passam pela mesma checagem de regex perigosa do `conflict_patterns` (UT-06).
- **Privacidade e dados pessoais:** itens confidenciais não saem pela exportação nem pelo conector, e só aparecem na busca com pedido explícito (IT-04, IT-05, UT-07).
- **Disponibilidade e resiliência:** frontmatter inválido não esconde nem revela nada por engano: só `confidential: true` (booleano) marca a nota (UT-02).
- **Acessibilidade (UI):** N/A — CLI e instruções.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:**

```text
Frontmatter (qualquer tipo de nota):
  confidential: true                              → nota confidencial (só o booleano true conta)
  vault_ref: "<esquema>://<caminho>"              → só em secret-ref; esquema [a-z][a-z0-9+.-]*, caminho não vazio

brain.py new-note --type secret-ref --title X --vault-ref REF [--context C] [--tags a,b] [--json]
  → nota com confidential: true e vault_ref, modelo assets/templates/secret-ref.md
  sem --vault-ref, ou REF fora do formato                                    → exit 2
  --vault-ref com outro tipo                                                 → exit 2
brain.py new-note --type T --title X --confidential [...]                    → mesmo modelo do tipo, com confidential: true

brain.py ingest ARQUIVO --confidential [--context C] [--title T] [--move] [--json]
  → copia (ou move, com --move) para files/ como hoje; nunca roda processador
  → nota de fonte com confidential: true, size (bytes), sha256 e "_(confidential: not extracted)_" no lugar do texto
  → --json: {"raw", "file", "url": null, "confidential": true}
  URL, --text-file, --kind ou --timestamps junto com --confidential           → exit 2

search | related | context | links  [--include-confidential]
  padrão: notas confidenciais ficam fora dos resultados, das vizinhas e dos links listados
  --json ganha "confidential_omitted": N (só o número)
  related --note <nota confidencial> | links <nota confidencial> sem a opção → exit 2 ("nota confidencial — use --include-confidential")
index: MOCs (região notes) e index.md (região recent) não listam notas confidenciais
export-notebooklm: nunca inclui nota confidencial (nem com opção); --json ganha "confidential_omitted": N
  wikilink de outra nota exportada que aponta para nota confidencial → texto "[confidencial]" (o título não sai)
  MOC confidencial → exit 2 ("MOC confidencial — …")
marca confidencial reconhecida com fim de linha CRLF e com BOM UTF-8

lint (regras novas, severidade AVISO, só em notas sem confidential: true, fora de templates):
  secret-in-note  <caminho>:<linha> — <tipo>   tipos: chave privada | token | senha rotulada
  personal-data   <caminho>:<linha> — <tipo>   tipos: cpf | cnpj | cartão | documento rotulado | <nome do padrão>
  o valor encontrado nunca é impresso; orphan não acusa nota confidencial
brain-config.yml (opcional):
  lint:
    personal_data: [cpf, cnpj, card, labeled-document]      # detectores ligados; padrão = todos
    personal_data_patterns: {nif: "\\bNIF:\\s*\\d{9}\\b"}   # extras; regex perigosa ou inválida = finding config

doctor: "OK confidential — N notas confidenciais" (só o número)
```

**Detectores:**
- `secret-in-note`: bloco `-----BEGIN ... PRIVATE KEY-----`; token com prefixo conhecido (`ghp_`, `github_pat_`, `AKIA` + 16, `xox[abpr]-`, `sk-` + 20 ou mais); rótulo (`senha`, `password`, `passwd`, `pwd`, `pin`, `token`, `api key`, `api_key`, `secret`, `segredo`) seguido de `:` ou `=` e de um valor de 4 ou mais caracteres sem espaço. Marcadores como `***`, `<...>`, `${...}`, texto entre chaves duplas e `xxx` não contam.
- `personal-data`: CPF (`000.000.000-00`, ou 11 dígitos logo depois do rótulo `CPF`) com os dígitos verificadores certos; CNPJ (`00.000.000/0000-00`, ou 14 dígitos depois de `CNPJ`) com os dígitos verificadores; cartão (13 a 19 dígitos em grupos separados por espaço ou hífen, ou depois de `cartão`/`card`) que passa no Luhn; documento rotulado (`RG`, `CNH`, `passaporte`, `passport`, `SSN`, `DNI`, `NIF`) seguido de `:` e de um valor com dígito. E-mail e telefone não contam.

**Instruções do agente (`SKILL.md` e `references/confidential.md`):**
- nunca escrever senha, token ou chave no vault, nem na inbox pelo conector; quando a pessoa der um segredo, não guardar, sugerir o gerenciador e oferecer a nota `secret-ref`;
- só usar `--include-confidential` quando a pessoa pedir, nesta conversa, para incluir itens confidenciais;
- no modo só conector, um arquivo com `confidential: true` não é citado nem resumido;
- nunca abrir o arquivo do gerenciador de senhas;
- para documento muito sensível, recomendar anexá-lo no próprio gerenciador (o KeePass e o KeePassXC aceitam anexos) e deixar no vault só a `secret-ref`; o vault no provedor não é cifrado pela pessoa;
- `references/confidential.md` mostra o KeePass/KeePassXC como exemplo e outros gerenciadores pelo mesmo formato, explica as regras do `lint`, os falsos positivos e os padrões extras.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Criar secret-ref | `new-note --type secret-ref --vault-ref keepass://Banco` | nota com `confidential: true` e `vault_ref`, exit 0 | IT-01 |
| secret-ref inválida | sem `--vault-ref`, REF fora do formato, ou `--vault-ref` com outro tipo | exit 2, nada criado | UT-01, IT-01 |
| Nota confidencial de outro tipo | `new-note --confidential` | modelo do tipo com `confidential: true` | IT-01 |
| Marca da nota | `confidential: true`, `"true"`, `yes`, ausente | só o booleano `true` marca | UT-02 |
| Documento confidencial | `ingest ARQ --confidential` (com e sem `--move`) | arquivo em files/, nota de fonte com size, sha256 e sem texto, processador não roda | IT-02, IT-03 |
| Ingest confidencial inválido | URL, `--text-file`, `--kind` ou `--timestamps` com `--confidential` | exit 2, nada criado | IT-02 |
| Busca padrão | vault com nota confidencial que casa com a busca | fora de `search`, `related`, `context` e `links`, `confidential_omitted` conta | UT-07, IT-04 |
| Busca pedida | `--include-confidential` | a nota aparece | IT-04 |
| Nota confidencial pedida pelo caminho | `related --note` ou `links` numa nota confidencial sem a opção | exit 2 | IT-04 |
| MOC e índice | `index` com nota confidencial no contexto | não listada no MOC nem no `recent` | IT-05 |
| Exportação | MOC que cita nota confidencial | nota fora do pacote, `confidential_omitted` conta | IT-05 |
| Título no pacote | nota exportada com `[[nota confidencial]]` | o link vira `[confidencial]`; MOC confidencial sai com 2 | IT-05 |
| Fim de linha e BOM | nota confidencial salva com CRLF ou BOM | continua confidencial em busca, índice, exportação e doctor | UT-02, IT-04, IT-05 |
| Segredo numa nota comum | chave privada, token, senha rotulada | AVISO `secret-in-note` com caminho, linha e tipo, sem o valor | UT-03, UT-05, IT-06 |
| Marcadores | `senha: ***`, `token: <seu token>` | nenhum achado | UT-03 |
| Dado pessoal numa nota comum | CPF, CNPJ e cartão válidos, documento rotulado | AVISO `personal-data`, sem o valor | UT-04, UT-05, IT-06 |
| Falso positivo evitado | CPF com dígito errado, cartão que não passa no Luhn, e-mail, telefone | nenhum achado | UT-04 |
| Nota confidencial no lint | nota com `confidential: true` e segredo dentro | sem achado de `secret-in-note`, `personal-data` nem `orphan` | IT-06 |
| Detectores configurados | `lint.personal_data: [cpf]` e um padrão extra | só os ligados e o extra rodam | UT-06 |
| Padrão extra perigoso | regex inválida ou com quantificador aninhado | finding `config`, as outras regras rodam | UT-06 |
| Doctor | vault com 2 notas confidenciais | `OK confidential — 2 notas confidenciais` | IT-07 |
| Instruções | `SKILL.md` e `references/confidential.md` | regras do agente, conector e gerenciador | UT-08 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — `search`, `related`, `context`, `links`, `index`, `export-notebooklm`, `ingest` e `lint` já têm testes das suas specs, e eles continuam valendo para as notas não confidenciais.

### 7.2 Testes Unitários
- **UT-01** — Dado valores de `vault_ref`, quando validados, então `keepass://Pessoal/Banco`, `bitwarden://item/abc` e `op://Vault/Item` passam, e `""`, `keepass:`, `://x`, `KeePass ://x` e `banco` não passam.
- **UT-02** — Dado frontmatters com `confidential: true`, `confidential: "true"`, `confidential: yes`, `confidential: false` e sem a chave, quando a nota é lida, então só o primeiro é confidencial.
- **UT-03** — Dado linhas com bloco de chave privada, `ghp_` + 36 caracteres, `AKIA` + 16, `xoxb-…`, `sk-` + 24, `senha: hunter22`, `password=abc123` e os marcadores `senha: ***`, `token: <seu token>`, `api_key: ${KEY}`, `pwd: xxx`, quando o detector de segredo roda, então só as sete primeiras geram achado, cada uma com o tipo certo.
- **UT-04** — Dado `123.456.789-09` (válido), `111.444.777-35` (válido), `123.456.789-00` (dígito errado), `CPF: 12345678909`, `11.222.333/0001-81` (CNPJ válido), `4111 1111 1111 1111` (Luhn ok), `4111 1111 1111 1112` (Luhn falha), `RG: 12.345.678-9`, `fulano@exemplo.com` e `(11) 98765-4321`, quando o detector de dado pessoal roda, então só os válidos e o RG rotulado geram achado, com o tipo certo.
- **UT-05** — Dado achados das duas regras, quando formatados (texto e `--json`), então trazem caminho, linha e tipo, e o valor encontrado não aparece em lugar nenhum da saída.
- **UT-06** — Dado `lint.personal_data: [cpf]` e `personal_data_patterns` com um padrão válido, um inválido e um com quantificador aninhado, quando o lint é montado, então só o CPF e o padrão válido rodam, e os outros dois viram finding `config`.
- **UT-07** — Dado notas, uma delas confidencial, quando `search`, `related`, `build_context` e `note_links` rodam sem incluir confidenciais, então a confidencial não aparece em resultados, vizinhas nem links, e a contagem de omitidas é 1; incluindo, ela aparece.
- **UT-08** — Dado `SKILL.md` e `references/confidential.md`, quando lidos, então trazem: nunca escrever segredo no vault nem na inbox; `--include-confidential` só com pedido da pessoa; no modo só conector, não citar nem resumir arquivo confidencial; nunca abrir o arquivo do gerenciador; a recomendação de anexar o documento no gerenciador; o exemplo do KeePass/KeePassXC e o formato `<esquema>://<caminho>` para outros gerenciadores; e as regras `secret-in-note` e `personal-data`.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init`, quando roda `new-note --type secret-ref --title "Banco" --vault-ref keepass://Pessoal/Banco --json` e `new-note --type note --title "Doc" --confidential`, então as notas têm `confidential: true` (e `vault_ref` na primeira); e sem `--vault-ref`, com `--vault-ref banco` ou com `--vault-ref` num tipo `note`, sai com 2 sem criar nada.
- **IT-02** — Dado um PDF e um processador de PDF configurado, quando roda `ingest doc.pdf --confidential --json`, então o arquivo vai para files/, a nota de fonte tem `confidential: true`, `size`, `sha256` (que confere com o arquivo) e `_(confidential: not extracted)_`, e o JSON tem `"confidential": true`; com URL, `--text-file`, `--kind pdf` ou `--timestamps`, sai com 2 sem criar nada.
- **IT-03** — Dado um processador que grava um marcador quando roda, quando `ingest --confidential` (com e sem `--move` a partir da inbox) roda, então o marcador não existe, e o `log.md` registra só o caminho da nota e o do arquivo.
- **IT-04** — Dado um vault com uma nota comum e uma confidencial que casam com "banco", quando roda `search banco --json`, `related --text banco --json`, `context banco --json` e `links` da nota comum, então a confidencial fica fora e `confidential_omitted` é 1; com `--include-confidential`, ela aparece; e `related --note` e `links` na nota confidencial, sem a opção, saem com 2.
- **IT-05** — Dado um contexto com uma nota comum e uma confidencial, ambas citadas pelo MOC, quando roda `index --context C` e `export-notebooklm C --out <pasta> --json`, então o MOC gerado e o `recent` do `index.md` não listam a confidencial, o pacote não tem a nota e `confidential_omitted` é 1.
- **IT-06** — Dado um vault com uma nota comum com `senha: hunter22` e `CPF: 123.456.789-09`, e uma nota confidencial com o mesmo texto e sem links, quando roda `lint --json` e `lint`, então há um AVISO `secret-in-note` e um `personal-data` só na nota comum, com a linha, sem `hunter22` nem o CPF na saída, nenhum `orphan` para a confidencial, e exit 0.
- **IT-07** — Dado um vault com duas notas confidenciais, quando roda `doctor`, então há a linha `OK confidential — 2 notas confidenciais`, e nenhum título ou caminho delas na saída.

### 7.4 Testes de Contrato
- N/A — sem contrato entre specs; os comandos são da própria skill e cobertos pelos testes de integração.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. O comportamento do agente é verificado nas instruções (UT-08).

### 7.6 Outros
- **Arquitetura (G3):** o teste do ADR-0014 garante que o caminho do `ingest --confidential` não chama `run_processor` (verificado no IT-03) e que nenhum código da skill importa biblioteca de criptografia ou de gerenciador de senhas (os imports continuam só da biblioteca padrão, teste do ADR-0007).

**Dublês e dados de teste:** vaults e configurações temporários com `HOME` e `BRAIN_CONFIG_HOME` isolados; processador falso que só grava um marcador; números de documento de exemplo, válidos só pelo algoritmo e sem pertencer a ninguém (`123.456.789-09`, `11.222.333/0001-81`, `4111 1111 1111 1111`).

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto. Notas sem `confidential` não mudam.
- **Dados/schema:** chaves novas e opcionais no frontmatter (`confidential`, `vault_ref`, `size`, `sha256`) e no `brain-config.yml` (`lint`).
- **Compatibilidade:** os filtros só excluem notas marcadas, e as duas regras novas são AVISO, então o exit do `lint` não muda para vault sem erro.
- **Observabilidade:** a linha `confidential` do `doctor` e os achados do `lint`.
- **Rollback:** `git revert` do merge. As notas marcadas continuam válidas (só voltam a aparecer na busca).
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Quais gerenciadores de senha você usa ou quer suportar na referência (KeePass/KeePassXC, Bitwarden, 1Password, outro)? (thomas) — KeePass/KeePassXC como exemplo documentado; os outros pelo mesmo formato `<esquema>://<caminho>`, sem código específico (thomas, 2026-11-02)
- [x] O arquivo `.kdbx` do KeePass deve ficar dentro da estrutura do segundo cérebro (em `files/`, como anexo opaco) ou continuar só onde está hoje, com a nota apontando para ele? (thomas) — continua onde está; a nota só aponta para ele (thomas, 2026-11-02)
- [x] Itens confidenciais devem ser totalmente invisíveis para a LLM (nem o título aparece na busca) ou só o conteúdo é protegido (o título e a referência aparecem)? (thomas) — invisíveis por padrão em busca, `context`, `related`, `links` e MOCs, e só aparecem com `--include-confidential` a pedido da pessoa; a exportação nunca inclui (thomas, 2026-11-02)
- [x] A regra do `lint` que acha "texto com cara de segredo" é desejada, mesmo podendo dar falso positivo? (thomas) — sim, como AVISO; e vale também para dados pessoais do dono do vault em documentos e notas (regra `personal-data`, com detectores configuráveis para manter a skill agnóstica de país), e documentos pessoais entram com `ingest --confidential` (thomas, 2026-11-02)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Marca confidencial, secret-ref e ingest opaco**
- [ ] Red: UT-01, UT-02, IT-01, IT-02 e IT-03 com a tag `SPEC-0050:<ID>`, falhando pelo motivo certo
- [ ] Green: `confidential`/`vault_ref`, `new-note --type secret-ref --vault-ref` e `--confidential`, `ingest --confidential` sem processador (size, sha256)
- [ ] Refactor mantendo tudo verde

**Fase 2: Fora de vista por padrão**
- [ ] Red: UT-07, IT-04 e IT-05 falhando pelo motivo certo
- [ ] Green: filtro em `search`, `related`, `context`, `links`, `index` e `export-notebooklm`, `--include-confidential` e `confidential_omitted`
- [ ] Refactor mantendo tudo verde

**Fase 3: Lint, doctor e instruções**
- [ ] Red: UT-03, UT-04, UT-05, UT-06, UT-08, IT-06 e IT-07 falhando pelo motivo certo
- [ ] Green: regras `secret-in-note` e `personal-data` (configuráveis, sem imprimir valor), `orphan` sem confidenciais, linha `confidential` do `doctor`, `SKILL.md`, `references/confidential.md` e as referências tocadas
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 29b2dc6 | 2026-11-02 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=31)) — c6aa6a9 | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 0192fc4 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 0192fc4 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (0192fc4; 2ª rodada após emenda v2: CRLF/BOM, [confidencial] no export, MOC confidencial exit 2, cartão de dígitos iguais, vault_ref fullmatch, ordem do lint; 2 nits de doc não bloqueantes) — 0192fc4 | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — e0ee5a7 | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0050`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-02 | Exportação troca wikilink para nota confidencial por `[confidencial]` e recusa MOC confidencial (exit 2); a marca vale com CRLF e BOM; cartão com dígitos todos iguais não conta | revisão G4: título da confidencial saía no pacote por links de outras notas, e notas CRLF/BOM vazavam | Nenhuma | thomas, 2026-11-02 ("pode fazer no piloto automático com o recomendado") |
