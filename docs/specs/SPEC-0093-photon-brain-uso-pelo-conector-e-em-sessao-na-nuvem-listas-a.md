---
id: SPEC-0093
title: "photon-brain: uso pelo conector e em sessão na nuvem (listas, achar o vault, fuso e sessão sem a pasta)"
tier: epic
type: feature
status: in-progress
created: 2026-11-23
depends_on: []
adrs: [ADR-0027]
external: []
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0093 — photon-brain: uso pelo conector e em sessão na nuvem (listas, achar o vault, fuso e sessão sem a pasta) (Épico)

> **Origem (thomas, 2026-11-23 a 2026-11-25):** primeiro feedback de uso real da photon-brain por conector, numa sessão na nuvem. Está registrado na inbox do vault, na nota `inbox/2026-11-23-020743-feedback-da-skill-second-brain-melhorias.md`; novos feedbacks entram na inbox do mesmo jeito. Um segundo feedback, do modo só conector no Google Drive (thomas, 2026-11-23), acrescentou os pontos 6 e 7 e detalhes nos pontos 3 e 5. Um terceiro, de uso real em 2026-11-25 (thomas), confirmou os pontos 1 a 6, trouxe detalhes nos pontos 3, 4 e 5 e acrescentou os pontos 8 a 11. Detalhado no G0 de 2026-11-26 nas filhas SPEC-0107 a SPEC-0113, sempre agnóstico e configurável. Os pontos:
> 1. **Lista que cresce:**
>    - pelo conector só dá para criar arquivo novo;
>    - uma lista que vai ganhando itens vira várias capturas soltas na inbox;
>    - falta um jeito de acrescentar a uma nota que já existe, ou de juntar as capturas depois.
> 2. **Tipo para listas:**
>    - nenhum tipo de nota serve para lista ou checklist;
>    - sugestão do usuário: um tipo `list` e um comando `list add`.
> 3. **Achar o vault no Drive:**
>    - foi preciso procurar o `brain-config.yml` para descobrir onde o vault fica;
>    - há várias pastas `inbox` antigas que confundem a busca;
>    - falta um jeito claro de identificar o vault e a inbox certos pelo conector;
>    - no segundo feedback, o caminho que funcionou foi buscar `title = 'brain-config.yml'` e depois a pasta `inbox` com o mesmo `parentId`;
>    - sugestões: documentar esse passo no `references/connectors.md`, ou guardar o ID da pasta inbox do Drive na config local;
>    - no terceiro feedback, a sugestão é guardar os IDs da pasta do vault e da inbox **por provedor**.
> 4. **Horário das capturas:**
>    - numa sessão na nuvem, a captura sai em UTC quando ninguém ajusta o fuso;
>    - o campo `created` vem sem o fuso;
>    - a ideia é gravar a data com o fuso e usar o fuso configurado do usuário;
>    - sugestão do terceiro feedback: um campo `timezone` no `brain-config.yml` e o `created` em ISO 8601 com o fuso.
> 5. **Sessão sem a pasta do vault:**
>    - sem a pasta conectada, nenhum fluxo completo de escrita funciona;
>    - o modo só conector resolve a captura, mas não dá para rodar `index`, `relate` nem processar a inbox;
>    - a skill deveria orientar a pedir só a pasta do vault;
>    - no terceiro feedback, pedir acesso a toda a pasta de nuvem do usuário e à config local foi negado, e só funcionou depois de conectar a pasta do vault;
>    - o SKILL.md deve explicar como conectar a pasta do vault ("Add folder") e deixar claro que, na nuvem, o `init --join` roda na máquina virtual da sessão, sem a config local do computador do usuário.
> 6. **Config ilegível pelo conector do Drive:**
>    - o `brain-config.yml` vem com o tipo `application/octet-stream`, e o `read_file_content` recusa esse tipo;
>    - sem ler a config, o `capture --print` não confere o `layout.inbox` nem se o contexto existe;
>    - sugestões: no `references/connectors.md`, orientar a ler o `.yml` com o `download_file_content`; ou manter uma cópia do layout e dos contextos num arquivo `.md` que o conector lê.
> 7. **Nome antigo na conta:**
>    - a sessão na nuvem do segundo feedback ainda carregou a skill com o nome `second-brain`, não a `photon-brain`;
>    - conferir se a conta tem uma versão antiga da skill ou o plugin antigo instalado, e se a SPEC-0067 cobre esse caso.
>
> 8. **Cópia da skill no vault sem os `assets/`:**
>    - uma cópia do `brain.py` guardada dentro do vault, para uso na nuvem, falhou porque procura `assets/brain-config.yml`;
>    - o remendo foi copiar `scripts` e `assets` juntos;
>    - a correção é o `brain.py` não depender de `assets/` quando o vault já tem `brain-config.yml`, ou um comando oficial que copia a skill inteira para o vault.
> 9. **Segredo na inbox sem alerta:**
>    - uma captura antiga da inbox tem senhas em texto, e o `lint --only secret-in-note` não acusou nada;
>    - aparentemente o `lint` não olha a `inbox/`;
>    - o `lint` e o `inbox list` devem olhar a inbox e avisar quando um item parece ter senha ou token, sem mostrar o valor.
> 10. **Acrescentar a uma nota que já existe:**
>    - para completar notas já existentes, as seções foram inseridas antes de `## Relations` com um script à mão, fora do `log.md`;
>    - sugestão: `append NOTA --section "Título" --text-file ARQ`, que insere antes de `## Relations` e registra no log.
> 11. **Corpo da nota criada pelo `new-note`:**
>    - o `new-note` cria só o esqueleto, e o corpo também foi escrito à mão, fora do log;
>    - sugestão: aceitar `--body-file ARQ` no `new-note`.
>
> Quarto bloco, do plano do ecossistema de vida (thomas, 2026-11-25; vault, contexto `ecossistema`, nota "Ecossistema de vida — arquitetura e decisões"):
>
> 12. **Inbox que separa ação de conhecimento:**
>    - ao processar a inbox, o que é ação ("comprar o gás até sexta") deve virar task no Google Tasks, na lista da área, e não nota;
>    - depende do MCP `google-tasks-mcp` (repositório próprio, SPEC-0001 de lá); a skill só orienta o agente a usar a ferramenta de tasks quando ela existir, sem chamar API nenhuma (a skill continua sem rede);
>    - o que tem hora marcada com outras pessoas vira sugestão de evento no Calendar.
> 13. **Contexto da área ligado às listas do Tasks:**
>    - cada contexto do `brain-config.yml` poderia declarar as listas do Tasks da área (ex.: `moradia` → Home Care, Home Maintenance, Groceries), para o agente saber onde criar a task;
>    - a tabela de áreas hoje vive só numa nota do vault.
> 14. **Nota de lista com check, e não task:**
>    - a lista de compras ficou duplicada entre o vault e o Tasks; a regra decidida é "o que se marca como feito vai para o Tasks, o que se consulta fica no vault";
>    - o tipo `list` do ponto 2 deve deixar isso claro, para não virar uma segunda lista de tarefas.
>
> Antes de detalhar, conferir as specs entregues de captura e inbox (SPEC-0021) e de configuração (SPEC-0017), para não repetir o que já existe.

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0093`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
A photon-brain funciona bem pelo conector e numa sessão na nuvem, e o vault cresce sem edição à mão nem dado solto.
- **Achar o vault e ler a configuração:** o agente acha o vault e a inbox certos pelos IDs que o próprio vault guarda e lê a configuração pelo conector.
- **Data e hora:** a captura sai com o fuso da pessoa.
- **Notas e listas:** notas e listas crescem pelo `brain.py`, com linha no log.
- **Cópia do script:** funciona sem a pasta `assets/`.
- **Segredos na inbox:** ficam visíveis para o `lint` e escondidos na prévia.
- **Ação ou conhecimento:** ao processar a inbox, a ação vira tarefa na lista da área e o conhecimento vira nota.

## 2. Escopo
**Objetivos (dentro do escopo):**
- Acrescentar a notas existentes e criar a nota com o corpo, com log (pontos 1, 10 e 11): SPEC-0107.
- Tipo `list` para listas de consulta e `list add`, com a regra "o que se marca como feito vai para as tarefas" (pontos 1, 2 e 14): SPEC-0108.
- Fuso do vault (`timezone`) nas datas, com o deslocamento no `created` da captura (ponto 4): SPEC-0109.
- IDs da pasta do vault e da inbox por provedor, e instruções do conector e da sessão na nuvem (pontos 3, 5, 6 e 7): SPEC-0110.
- `brain.py` copiado sozinho, sem `assets/` (ponto 8): SPEC-0111.
- Segredo na inbox detectado e mascarado (ponto 9): SPEC-0112.
- Inbox que separa ação de conhecimento e as listas de tarefas por contexto (pontos 12 e 13): SPEC-0113.

**Não-objetivos (fora do escopo):**
- O `brain.py` chamar qualquer API (provedor, tarefas, agenda), conforme o ADR-0008 e o ADR-0027.
- Editar ou mover arquivos do vault pelo conector além de criar o arquivo novo na inbox (ADR-0013).
- Remover a skill antiga da conta do claude.ai, que é ação da pessoa (só fica documentado, SPEC-0110).
- Checklist e tarefas dentro do vault.

## 3. Arquitetura Alvo
**Contexto:** projeto existente. A arquitetura da photon-brain é a dos ADR-0007 (fronteiras, sem rede, escrita só pelo `brain.py` com log), ADR-0008 (vault no provedor de arquivos), ADR-0013 (conector do agente só cria arquivo novo na inbox e lê) e ADR-0014 (confidenciais). Nada disso muda.

Ao final:
- **`brain.py`:** ganha `append`, `new-note --body-file`, o tipo `list` com `list add`, `connector set|show`, `context set` e `inbox done --outcome`.
- **`brain-config.yml`:** ganha as chaves opcionais `timezone`, `connectors.<provedor>` e `contexts.<nome>.tasks`.
- **Detector de segredos:** passa a cobrir os itens de texto e de link da inbox.
- **Padrões embutidos:** o `brain.py` passa a ter os padrões da configuração embutidos.
- **Instruções:** o `SKILL.md` e as referências ganham o roteiro do conector, da sessão na nuvem e do processamento da inbox com ação e conhecimento separados.
- **Contratos entre filhas:** nenhum entre specs paralelas. A SPEC-0108 usa a escrita da SPEC-0107 e a SPEC-0113 usa a regra de listas da SPEC-0108, as duas por `depends_on`.

**Decisões (ADRs):** ADR-0027: integrações do agente por orientação e configuração no vault, nunca pelo `brain.py`.

**Regras de arquitetura a garantir (G3):**
- `brain.py` sem módulo de rede (`tests/test_architecture.py`, ADR-0007).
- Os padrões embutidos iguais ao `assets/brain-config.yml` (regra nova da SPEC-0111).

## 4. Decomposição
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0107 | acrescentar a notas existentes (`append` e `new-note --body-file`) | full | feature | M | — | — |
| SPEC-0108 | tipo `list` para listas de consulta e `list add` | full | feature | M | SPEC-0107 | — |
| SPEC-0109 | fuso horário nas datas das capturas e do log | full | feature | M | — | — |
| SPEC-0110 | conector e sessão na nuvem: achar o vault, ler a config e conectar só a pasta | full | feature | M | — | — |
| SPEC-0111 | `brain.py` sem `assets/` quando o vault já tem a configuração | full | feature | S | — | — |
| SPEC-0112 | segredo na inbox: `lint` e `inbox list` avisam sem mostrar o valor | full | feature | M | — | — |
| SPEC-0113 | inbox que separa ação de conhecimento e listas de tarefas por contexto | full | feature | M | SPEC-0108 | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A. A skill chega pelo plugin `fermion` depois de cada merge (pilar de entrega dispensado no `sdd-config.yml`).
- **Entrega por onda:**
  - As filhas tocam o `brain.py`, o CHANGELOG e o `plugin.json`, então rodam uma de cada vez. A ordem segue o valor para o uso real:
    1. 0107 (`append`);
    2. 0109 (fuso);
    3. 0110 (conector e nuvem);
    4. 0112 (segredos);
    5. 0111 (script sozinho);
    6. 0108 (listas);
    7. 0113 (ação e conhecimento).
  - Cada merge sobe a versão do plugin e a `BRAIN_VERSION`.
- **Feature flags:** N/A. Todas as mudanças são opcionais ou aditivas.
- **Rollback:** reverter o merge da filha. As chaves novas são opcionais, e o vault continua válido.
- **Métricas de sucesso pós-release:** no uso real, nas próximas semanas:
  - nenhum texto escrito à mão fora do log;
  - capturas com o fuso certo na nuvem;
  - a sessão no celular ou na nuvem acha o vault sem procurar;
  - itens de ação da inbox indo para o Tasks.

## 6. Riscos & Mitigações
- **O conector do Drive mudar de nome ou de ferramenta:** as instruções tratam os nomes como os de hoje e dão a alternativa (seguir com `inbox` e avisar); a SPEC-0110 registra a data da conferência.
- **Falso positivo no detector de segredos:** os casos negativos ficam nos testes da SPEC-0112 e os valores-marcador continuam ignorados.
- **Fuso ausente na base da máquina (Windows):** a mensagem diz o que instalar e o comando não grava data errada (SPEC-0109).
- **O agente não seguir o roteiro de ação e conhecimento:** o `inbox done --outcome` deixa rastro no log; sem ferramenta de tarefas, o item fica na inbox.

## 7. Critérios de Aceite do Épico
- [ ] Uma seção acrescentada a uma nota existente e o corpo de uma nota nova entram pelo `brain.py`, com linha no log — SPEC-0107:IT-01, SPEC-0107:IT-02
- [ ] Uma lista de consulta cresce com `list add`, sem itens repetidos e sem checklist — SPEC-0108:IT-01
- [ ] Numa máquina em UTC, a captura de um vault com `timezone` sai com a hora e o deslocamento do fuso da pessoa — SPEC-0109:IT-01
- [ ] Os IDs do vault e da inbox ficam no vault, e as instruções levam a sessão só com conector à inbox certa e à leitura do `.yml` — SPEC-0110:IT-01, SPEC-0110:UT-06
- [ ] O `brain.py` copiado sozinho para dentro do vault roda o fluxo de captura e processamento — SPEC-0111:IT-01
- [ ] Senhas em itens da inbox são acusadas pelo `lint` e mascaradas no `inbox list`, sem o valor em nenhuma saída — SPEC-0112:IT-01
- [ ] Um item de ação da inbox é fechado como tarefa da lista da área, e um de conhecimento como nota — SPEC-0113:IT-01

## 8. Questões em Aberto
- [x] Os pontos 12 a 14 ficam neste épico ou num do ecossistema? — Ficam aqui: na photon-brain, eles são configuração e roteiro de processamento da inbox; a ferramenta de tarefas é do repositório próprio (Architect, 2026-11-26, no piloto automático)
- [x] O ponto 7 (nome antigo na conta) é código? — Não. É a skill antiga avulsa na conta do claude.ai; a SPEC-0110 documenta como reconhecer e o que fazer, e a remoção é da pessoa (anotada na inbox do vault)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0093` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
