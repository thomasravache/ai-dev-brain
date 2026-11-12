---
name: photon-brain
description: >-
  Segundo cérebro (antes `second-brain`) num vault do Obsidian mantido com uma LLM: notas Markdown em PARA, contextos com MOC, inbox, índice e log, sincronizado por Google Drive, OneDrive, iCloud ou pasta local, em várias máquinas e no celular. Use para configurar (onboarding de vault novo ou existente, máquina nova), ver a configuração, criar contexto, diagnosticar (doctor); buscar notas, relacionadas e links (search, related, links); guardar anotação, aula, PDF, vídeo ou link (ingest, new-note, relate, index), extraindo texto de YouTube, vídeo, áudio e PDF (process); perguntar ao segundo cérebro ("o que eu sei sobre X", "me prepara para a prova": context, nota answer); capturar e processar a inbox, inclusive do celular ("anota isso", "processa minha inbox": capture, inbox list, ingest --move, inbox done); ou manter o vault ("tem link quebrado?": lint). Guarda itens confidenciais sem expor segredos (secret-ref, --confidential).
---

# Photon Brain

Esta skill se chamava `second-brain`; pedidos por esse nome são para ela. A ferramenta, a configuração da máquina (`~/.config/second-brain`) e os nomes de backup continuam com o nome antigo.

Você ajuda a pessoa a manter um vault do Obsidian como segundo cérebro. O vault é **dela**: você nunca apaga nem sobrescreve uma nota, e tudo o que é determinístico (pastas, configuração, MOCs, log, diagnóstico) é feito pelo `scripts/brain.py`, nunca à mão.

A skill é **agnóstica de provedor e de agente**: o vault é só uma pasta sincronizada pelo app do provedor, e o `brain.py` só precisa de Python 3.9+.

## Ferramenta

Rode `python3 <skill-dir>/scripts/brain.py <comando>`, onde `<skill-dir>` é a pasta deste `SKILL.md`.

| Comando | Uso |
|---|---|
| `config [--json]` | Configuração efetiva, com a origem de cada valor (`local`, `vault` ou `padrão`). Exit 3 = não configurado nesta máquina |
| `init --vault P --files F --provider X [--adopt [--map chave=pasta ...]] [--context nome=pasta[:título] ...] [--force]` | Cria um vault novo ou adota um existente sem mover nem alterar arquivos; grava as duas configurações |
| `init --join --vault P --files F --provider X` | Máquina nova para um vault que já tem `brain-config.yml`: grava só a configuração local |
| `context add NOME --folder PASTA [--title T]` | Registra um contexto, cria a pasta e o MOC `mocs/NOME.md` |
| `context QUERY [--context C] [--hops N] [--limit N] [--max-chars N] [--include-confidential] [--json]` | Pacote de notas para uma pergunta, só leitura: o MOC do contexto (com `--context`), os resultados da busca (até `--limit`, padrão 8) e os vizinhos por link até `--hops` passos (0 a 2, padrão 1), notas inteiras até `--max-chars` (padrão 40000; a que não cabe vai para `omitted` e as seguintes continuam sendo tentadas; o MOC nunca é atravessado), links quebrados em `broken`. Sem resultado imprime "Nenhuma nota encontrada para: …" e sai com 0; `--hops` fora de 0..2 sai com 2. Se a primeira palavra é exatamente `add`, é o `context add` acima (para buscar a palavra add: `context --json add`). Notas confidenciais ficam fora (nem como link quebrado) e o `--json` conta quantas em `confidential_omitted` |
| `doctor [--json]` | Uma linha `OK\|AVISO\|ERRO <item> — <detalhe>` por item (inclusive `OK confidential — N notas confidenciais`, só o número, e uma linha `OK\|AVISO backup <destino> — …` por destino de backup); exit 0 sem ERRO, 1 com ERRO, 3 sem configuração |
| `search QUERY [--context C] [--type T] [--tag G] [--limit N] [--include-confidential] [--json]` | Busca por termos, com pontuação e um trecho de cada nota; sem resultado imprime "Nenhuma nota encontrada para: …" e sai com 0. Notas confidenciais ficam fora, a menos que `--include-confidential`; o `--json` conta as omitidas em `confidential_omitted` |
| `related (--note CAMINHO \| --text TEXTO) [--limit N] [--include-confidential] [--json]` | Notas parecidas com uma nota ou com um texto, cada uma com os motivos; nota inexistente sai com 2. Sem `--include-confidential`, notas confidenciais ficam fora (`confidential_omitted` no `--json`) e `--note` numa nota confidencial sai com 2 |
| `links NOTA [--include-confidential] [--json]` | Links de saída (resolvidos ou quebrados) e backlinks de uma nota, pelo caminho ou pelo nome; inexistente sai com 2. Sem `--include-confidential`, links de e para notas confidenciais ficam fora (`confidential_omitted`) e uma nota confidencial sai com 2 |
| `ingest FONTE [--context C] [--title T] [--text-file ARQ] [--kind K] [--no-process] [--timestamps] [--json]` | Arquivo: copia para `<files>/<contexto ou inbox>/<AAAA>/` sem sobrescrever (`-1`, `-2`...); URL: nada é copiado. Cria a nota de fonte `raw/AAAA-MM-DD-<slug>.md` com o texto sob `## Extracted text`: o de `--text-file`, ou o do processador do tipo (youtube, video, audio, pdf; `--no-process` desliga, `--timestamps` põe `[mm:ss]`), ou `_(pending)_` com o aviso "sem processador para <tipo>". Falha do processador: aviso, `_(extraction failed: <motivo>)_` na nota e exit 0. Fonte inexistente sai com 2; pasta `files` inacessível sai com 1 |
| `ingest ARQUIVO --confidential [--context C] [--title T] [--move] [--json]` | Documento confidencial: o arquivo vai para `files` como no `ingest` (ou sai da inbox com `--move`), **nunca** roda processador e a nota de fonte só tem `confidential: true`, `size`, `sha256` e `_(confidential: not extracted)_`; `--json` traz `"confidential": true`. URL, `--text-file`, `--kind` ou `--timestamps` junto saem com 2 |
| `process ENTRADA [--kind K] [--out ARQ] [--timestamps]` | Roda o processador do tipo e imprime o texto (ou grava em `--out`, que só cria arquivo novo fora do vault: ARQ que já existe sai com 2 "já existe: <ARQ>", ARQ dentro do vault sai com 2), sem escrever no vault. Sem processador sai com 2 ("nenhum processador para <tipo> — veja references/processors.md"); falha sai com 1 ("processador <tipo> falhou: <motivo>") |
| `new-note --type T --title X [--context C] [--source S] [--tags a,b] [--confidential] [--json]` | Cria a nota a partir do modelo do tipo, na pasta do contexto (sem contexto, `resources/`); imprime o caminho. Nota existente, tipo ou contexto inválido saem com 2. `--confidential` grava `confidential: true` |
| `new-note --type secret-ref --title X --vault-ref REF [--context C] [--tags a,b] [--json]` | Nota que diz onde um segredo está no gerenciador de senhas, sem o segredo: `confidential: true` e `vault_ref: REF` (`<esquema>://<caminho>`, ex.: `keepass://Pessoal/Banco`). Sem `--vault-ref`, REF fora do formato ou `--vault-ref` com outro tipo saem com 2 |
| `relate DE PARA --why "motivo" [--both]` | Acrescenta `- [[PARA]] — motivo` na seção `## Relations` de DE (e de PARA com `--both`); repetida = "relação já existe" |
| `index [--context C]` | Regenera as regiões geradas dos MOCs (`notes`) e do `index.md` (`contexts`, `recent`), sem tocar no texto da pessoa |
| `capture TEXTO [--context C] [--json]` | Nota rápida `inbox/AAAA-MM-DD-HHMMSS-<slug>.md` (`type: capture`); imprime o caminho. `--inbox` só vale com `--print` (sem ele sai com 2). Texto vazio sai com 2 |
| `capture TEXTO --print [--context C] [--inbox PASTA] [--json]` | Não escreve nada e não exige configuração: mostra o caminho (relativo ao vault) e o conteúdo que o `capture` gravaria, `"<caminho>\n\n<conteúdo>"` ou, com `--json`, `{"path", "content"}`, para enviar pelo conector (modo só conector). Com o `brain-config.yml` do vault legível usa `layout.inbox` e valida o contexto (inválido sai com 2); sem configuração, ou com o vault, o `brain-config.yml` ou a inbox ausente ou ilegível, não falha: usa `inbox`, ou o `--inbox` informado, e sai com 0. `--inbox` com o `brain-config.yml` legível sai com 2 (a pasta é a do `layout.inbox`); `--inbox` na raiz do vault (`""`, `.`) ou fora dele (`..`, caminho absoluto) sai com 2. Texto vazio sai com 2 |
| `inbox list [--json]` | Itens da inbox, do mais antigo para o mais novo: `path`, `kind` (`text`, `link`, `file` ou `syncing`), `size`, `age_days`, `stale` (mais velho que `inbox_stale_days`, padrão 7) e `preview`. Vazia imprime "Inbox vazia" |
| `ingest ITEM --move [--context C] [...]` | Como o `ingest`, mas o arquivo **sai** da inbox para `files` em vez de ser copiado. Fonte fora da inbox sai com 2 ("--move só vale para itens da inbox"); item `syncing` sai com 2 |
| `lint [--json] [--only regra,...]` | Achados de manutenção, só leitura: `broken-link`, `conflict-copy`, `missing-file` e `config` (erro); `orphan`, `stale-inbox`, `frontmatter`, `secret-in-note` e `personal-data` (aviso; caminho, linha e tipo, nunca o valor). Uma linha `<ERRO\|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)` por achado e o resumo "N erros, M avisos"; exit 0 sem erro, 1 com erro, 2 com regra desconhecida em `--only` |
| `export-notebooklm MOC --out PASTA [--hops 0..2] [--combined] [--json]` | Pacote de um MOC para subir no NotebookLM, só lendo o vault: o MOC, as notas que ele cita e as vizinhas delas até `--hops` (padrão 1; o MOC, o `index.md` e o `log.md` nunca são atravessados), um `.md` por nota com o título no topo e os wikilinks como texto, `sources.md` (de onde veio cada nota) e, com `--combined`, `combined.md`. `--out` dentro do vault ou já com arquivos sai com 2 (nunca sobrescreve); `--hops` fora de 0..2 ou MOC inexistente sai com 2. Nota confidencial nunca é exportada (`confidential_omitted` no `--json`), e um link para ela em outra nota vira `[confidencial]`, sem o título; MOC confidencial sai com 2 |
| `inbox done ITEM [--note CAMINHO]` | Item `text` ou `link` já guardado vai para `raw/processed/AAAA-MM/` (nunca sobrescreve: `-1`, `-2`...) e o log cita a nota. `file` sai com 2 ("arquivo: use ingest --move"), `syncing` sai com 2 ("ainda sincronizando") |
| `backup target add PASTA` | Acrescenta PASTA (absoluta) aos destinos de backup desta máquina (`backup_targets` da configuração local); repetida = "destino já existe" (exit 0); dentro do vault ou da pasta `files` sai com 2 |
| `backup [--dest PASTA ...] [--with-files] [--json]` | Um zip `second-brain-AAAA-MM-DD-HHMMSS[-files].zip` em cada destino (`--dest` substitui os destinos nesta execução), gravado como `.partial`, verificado e renomeado; depois a rotação mantém os `backup.keep` mais recentes do padrão (padrão 10) e nunca toca outros arquivos. Linha no `log.md`. Sem destino ou destino dentro do vault ou de `files` sai com 2; destino que falha não impede os outros e o exit é 1 |
| `backup list [--json]` | Backups de cada destino, do mais novo para o mais velho (nome, data, tamanho, entradas, `with_files`); destino inacessível aparece com o motivo; exit 0 |
| `backup verify [ZIP] [--json]` | `OK <zip> — N entradas` ou `ERRO <zip> — <motivo>` (sem ZIP: o mais novo de cada destino; destino inacessível = `AVISO`); exit 0, 1 com erro, 2 com ZIP inexistente |
| `restore NOTA --from ZIP [--json]` | Grava `<pasta>/<nome> (restaurado AAAA-MM-DD).md` no vault (`-1`, `-2`... se existir), nunca sobrescreve a nota atual; linha no `log.md`. NOTA fora do zip sai com 2; zip que não verifica sai com 1 |
| `restore --from ZIP --to PASTA [--json]` | Extrai `vault/` (e `files/`) para uma pasta nova ou vazia, fora do vault e de `files`; pasta com arquivos sai com 2; entrada com `..` ou caminho absoluto sai com 1 sem gravar nada |

Pontuação e filtros de `search` e `related`: `references/search.md`. Fluxo de consultar e o pacote do `context`: `references/query-flow.md`. Fluxo de guardar em detalhe: `references/store-flow.md`; tipos de nota e frontmatter: `references/note-types.md`. Detalhes das duas camadas de configuração: `references/config.md`. Estrutura do vault: `references/vault-layout.md`. Provedores e celular: `references/providers.md`. Inbox em detalhe: `references/inbox.md`; capturar pelo celular: `references/mobile-capture.md`; capturar e consultar pelo conector do provedor: `references/connectors.md`. Processadores (modelos de yt-dlp, Whisper e pdftotext): `references/processors.md`. Exportar para o NotebookLM (envio, formatos e limites): `references/notebooklm.md`. Manutenção e as regras do `lint`: `references/maintenance.md`; padrões de cópia de conflito por provedor: `references/providers.md`. Itens confidenciais, `secret-ref` e gerenciador de senhas: `references/confidential.md`.

## Antes de qualquer fluxo

Rode sempre `brain.py config` antes de qualquer fluxo, em toda conversa — não confie na memória:

- **Configurado (exit 0)** → siga direto o fluxo pedido, sem perguntar nada de configuração.
- **Exit 3** sem conector do provedor (ou quando a pessoa pedir para configurar esta máquina) → faça o **onboarding** abaixo, ou o `init --join` se o vault já existir configurado.
- **Exit 1** ou valores estranhos → rode `brain.py doctor` e mostre o resultado antes de seguir.
- **Sem enxergar o vault** — exit 3, ou exit 1 de um vault que o agente não consegue ler (pasta do vault ou `brain-config.yml` inacessível, como quando o macOS bloqueia a pasta do provedor), ou exit 0 com a pasta do vault inacessível, ou sem shell — e com um conector do provedor na ferramenta → **modo só conector** (seção abaixo), só para capturar e consultar. Essa regra vem antes das de exit 3 e exit 1 acima, a menos que a pessoa queira configurar esta máquina (onboarding ou `init --join`) ou consertá-la (`doctor`): aí siga o fluxo de configuração.

**Exit 3 numa sessão nova é normal**, não um problema para resolver: a configuração local fica na máquina e não acompanha sessões na nuvem ou no celular. Com um conector do provedor na ferramenta, antes de pensar em onboarding, busque o arquivo `brain-config.yml` pelo conector. Achou → o vault é a pasta dele: entre direto no modo só conector, sem perguntar nem comentar sobre configuração. Vá para o onboarding só se o conector não achar o `brain-config.yml`, ou se a pessoa pedir para configurar esta máquina. Se o pedido não couber no modo só conector, explique o limite em uma frase.

## Onboarding (exit 3 sem conector, ou a pedido)

Converse com a pessoa; o `brain.py init` não é interativo e recebe tudo por flags.

1. **Provedor:** pergunte onde o vault vai ficar — `google-drive`, `onedrive`, `icloud` ou `local`. Avise sobre o celular conforme `references/providers.md` (ex.: no iPhone, Google Drive e OneDrive não são suportados oficialmente pelo Obsidian; iCloud é o recomendado entre aparelhos Apple; o Obsidian Sync funciona em todos).
2. **Vault novo ou existente:** pergunte se ela já tem um vault.
   - Já tem e ele tem `brain-config.yml` (configurado em outra máquina) → vá para **Máquina nova** abaixo.
   - Já tem, sem `brain-config.yml` → é uma adoção (`--adopt`): pergunte quais pastas ela já usa para inbox, projetos, áreas, recursos e arquivo, e passe cada uma com `--map` (ex.: `--map inbox=Inbox`). Nada existente é movido ou alterado. Se ela já tem um `log.md` ou `index.md` próprio, o `init` sai com 2: passe `--map log=<outro>` (ou `--map index=<outro>`).
   - Não tem → vault novo. Uma pasta que só tem `.obsidian/` (vault recém-criado no app do Obsidian) conta como vazia: o `init` sem `--adopt` cria a estrutura padrão e não mexe em `.obsidian/`.
3. **Caminhos:** pergunte onde ficam o vault (dentro da pasta sincronizada do provedor) e a pasta de arquivos pesados (`files`, fora do vault, no mesmo provedor). Sugira nomes em kebab-case (minúsculas, sem acento, palavras separadas por `-`), como `~/second-brain/vault` e `~/second-brain/files` dentro da pasta do provedor; o `doctor` avisa quando a pasta do vault, a de `files` ou a pasta que contém cada uma não segue o padrão, sem renomear nada.
4. **Contextos iniciais:** pergunte os assuntos principais (ex.: faculdade, trabalho) e passe cada um com `--context nome=pasta[:título]` (ex.: `--context college=projects/college:College`). O nome e cada parte da pasta viram kebab-case (`Trabalho Novo` → `trabalho-novo`, com o aviso "nome ajustado para kebab-case"); o título fica como ela escreveu.
5. **Processadores:** pergunte quais tipos ela quer converter em texto (vídeos do YouTube, vídeos e áudios, PDFs) e ofereça os modelos de `references/processors.md` (yt-dlp, Whisper, pdftotext). A skill não instala nada: confira com ela se a ferramenta já existe; depois do `init`, copie os modelos escolhidos para `processors` no `brain-config.yml` do vault e avise que o yt-dlp acessa a rede. O `doctor` (passo 7) testa cada processador.
6. Rode o `brain.py init` com as flags e mostre o que foi criado. Se ele sair com 2 dizendo que o `brain-config.yml` já existe, pergunte se ela quer `--join` (usar o que existe) ou `--force` (substituir; o anterior fica em `brain-config.yml.bak`). Nunca use `--force` sem o sim dela.
7. Rode `brain.py doctor` e mostre o resultado, explicando cada AVISO e ERRO.

Exemplo de vault novo:

```bash
python3 <skill-dir>/scripts/brain.py init --vault "<vault>" --files "<files>" --provider icloud \
  --context college=projects/college:College
python3 <skill-dir>/scripts/brain.py doctor
```

## Máquina nova (`init --join`)

Vault com `brain-config.yml` e máquina sem configuração local: pergunte só o provedor e os caminhos do vault e da pasta `files` **nesta** máquina e rode `brain.py init --join --vault P --files F --provider X`. Só a configuração local é gravada; contextos, layout e processadores vêm do vault. Depois, `brain.py doctor`.

## Contextos

Para um assunto novo, rode `brain.py context add NOME --folder PASTA --title T` (pasta relativa ao vault). O nome e cada parte da pasta viram kebab-case, com o aviso "nome ajustado para kebab-case: `<de>` → `<para>`"; um nome ou parte só de símbolos sai com 2. Contexto que já existe sai com 2: não crie outro com o mesmo nome. O `context add` só vale quando `add` é a primeira palavra depois de `context`; qualquer outro texto depois de `context` é uma consulta (seção **Consultar o segundo cérebro**).

## Buscar e relacionar notas

`search`, `related` e `links` só leem o vault (nada é escrito) e não usam rede nem índice: leem as notas a cada execução. Use sempre `--json` para ler os resultados; avisos de notas com frontmatter inválido ou que não são UTF-8 vêm em `warnings` e não impedem o comando — mencione-os à pessoa se forem relevantes.

- **Fluxo de guardar** (seção abaixo; nota nova a partir da inbox, de uma fonte ou de uma conversa): antes de escrever, rode `brain.py related --text "<resumo do conteúdo novo>" --json` e `brain.py search "<termos principais>" --json` para buscar relações. Leia as notas mais bem pontuadas e use os motivos (`tags:`, `mesmo contexto`, `link direto`, `termos:`) para decidir os `[[links]]`, as tags e o contexto da nota nova — e se o conteúdo já existe numa nota que deveria ser complementada em vez de duplicada.
- **Fluxo de consultar** (responder uma pergunta com base no vault; passos na seção **Consultar o segundo cérebro**): o `brain.py context` já faz o `search` e segue os links até as vizinhas. Quando faltar algo, rode `brain.py search "<outros termos>" --json` (com `--context`, `--type` ou `--tag`), `brain.py links NOTA --json` para seguir os links de saída e os backlinks de uma nota central, e `brain.py related --note CAMINHO --json` para ampliar a partir dela.
- **Links quebrados:** `links` lista em `broken` os alvos que não existem; mostre-os à pessoa, sem criar nem corrigir notas por conta própria.

A busca é por termos (sem acentos e sem diferenciar maiúsculas), não semântica: se nada vier, tente sinônimos e termos mais curtos antes de concluir que o vault não tem a informação.

## Guardar no segundo cérebro

Para guardar qualquer coisa (anotação, aula, PDF, vídeo, link ou o resumo de uma conversa), siga sempre estes seis passos, nesta ordem. Detalhes e exemplos: `references/store-flow.md`.

1. **Classificar:** escolha o tipo (`note`, `lecture`, `source`, `video`, `document`, `link` ou `moc`, conforme `references/note-types.md`) e o contexto; senha, token ou documento pessoal seguem a seção **Itens confidenciais e segredos**. Pergunte o contexto só se for ambíguo; se nenhum servir, sugira criar um com `brain.py context add`.
2. **Guardar o bruto:** arquivo ou link → `brain.py ingest FONTE --context C --json`. Vídeo do YouTube, vídeo, áudio ou PDF com processador configurado (`references/processors.md`): o `ingest` extrai o texto sozinho (`--timestamps` em aula gravada, para citar o trecho); leia a nota de fonte criada para sintetizar. Sem processador, ou se a extração falhou (`_(extraction failed: …)_`), e você consegue ler o arquivo (ou a página): grave o texto num arquivo temporário e passe `--text-file ARQ` (tem prioridade sobre o processador); senão a nota de fonte fica com `_(pending)_`. Guarde o caminho `raw` devolvido.
3. **Buscar relações:** antes de escrever, rode `brain.py related --text "<resumo do conteúdo>" --json` (e `brain.py search "<conceitos principais>" --json`). Leia as notas mais bem pontuadas e decida quais se ligam à nova — e se o conteúdo já existe numa nota que deveria ser complementada.
4. **Escrever:** `brain.py new-note --type T --title X --context C --source <raw> --json` e, em seguida, escreva o corpo sintetizado no arquivo criado, no idioma do conteúdo (resumo com as suas palavras, seções do modelo). Nunca altere texto escrito pela pessoa em outras notas.
5. **Ligar e indexar:** para cada relação relevante, `brain.py relate "<nota nova>" "<outra>" --why "<motivo>" --both` (ex.: "aplica", "contradiz", "exemplo de", "pré-requisito de"); depois `brain.py index --context C`.
6. **Reportar:** diga à pessoa a nota criada (caminho), as relações e por quê, e os insights — ligações novas ou lacunas que apareceram.

A seção `## Relations` de cada nota tem uma linha por relação, sempre neste formato (o `relate` escreve assim):

```markdown
## Relations

- [[Regra do produto]] — aplica
```

Regras de síntese: a nota é uma síntese, não uma cópia — o texto bruto fica na nota de fonte em `raw/`; uma ideia por nota quando der; `[[links]]` só para notas que existem (ou que você acabou de criar).

## Consultar o segundo cérebro

Para responder uma pergunta com base no vault ("o que eu sei sobre X", "me prepara para a P2 de Cálculo II"), siga sempre estes quatro passos, nesta ordem. A resposta vem das notas da pessoa, não da sua memória. Detalhes e exemplo: `references/query-flow.md`.

1. **Buscar:** rode `brain.py context "<termos da pergunta>" --json`, com `--context C` quando a pergunta é de um contexto (o MOC dele vem primeiro). Se nada vier, tente sinônimos e termos mais curtos.
2. **Ler e seguir links:** leia o pacote (`notes`; `omitted` traz só o título do que não coube, e `broken` os links quebrados). Se faltar algo, rode `brain.py related --note CAMINHO --json` e `brain.py links CAMINHO --json` nas notas centrais e leia as que importarem.
3. **Responder:** cada afirmação vinda do vault cita a nota de onde veio, como `[[Integrais por partes]]`; o que vier de conhecimento geral (fora do vault) é marcado como tal; aponte as lacunas — o que a pergunta pede e o vault não tem.
4. **Oferecer salvar:** pergunte se a pessoa quer guardar a resposta. Só com o sim dela: `brain.py new-note --type answer --title "<pergunta curta>" --context C --json`, escreva a pergunta, a resposta e as lacunas nas seções do modelo (e `question`/`cites` no frontmatter), rode `brain.py relate "<answer>" "<nota citada>" --why "cita" --both` para cada nota citada e depois `brain.py index --context C`.

Quando a pessoa vai estudar ou se preparar para uma prova ("me prepara para a prova"), ofereça também o pacote do MOC para o NotebookLM: só com o sim dela, rode `brain.py export-notebooklm C --out <pasta nova fora do vault>` (com `--combined` se ela quiser poucas fontes) e explique o envio conforme `references/notebooklm.md`.

## Capturar e processar a inbox

A `inbox/` é a porta de entrada: capture sem pensar e organize depois. No computador, "anota isso: …" vira `brain.py capture "<texto>" [--context C]`. No celular a pessoa joga qualquer coisa na pasta `inbox/` pelo app do provedor ou pelo Obsidian mobile (`references/mobile-capture.md`); o celular não roda a skill.

Para processar a inbox ("processa minha inbox"), siga sempre estes quatro passos, nesta ordem. Detalhes: `references/inbox.md`.

1. **Listar:** rode `brain.py inbox list --json` e mostre quantos itens há e quais estão parados (`stale`).
2. **Guardar cada item:** para cada item, do mais antigo para o mais novo, siga o fluxo de guardar (seção **Guardar no segundo cérebro**): arquivo (`file`) → `ingest --move` (`brain.py ingest ITEM --move --context C --json`: o arquivo sai da inbox para `files`) e a nota a partir da nota de fonte; texto ou link → leia o item e escreva a nota com `new-note` (link: `ingest URL` antes, para a nota de fonte).
3. **Tirar da inbox:** item de texto ou link já guardado → `brain.py inbox done ITEM --note <nota criada>` (vai para `raw/processed/AAAA-MM/`; nada é apagado).
4. **Pular e reportar:** pule os itens `syncing` (ainda sincronizando; não processe) e avise a pessoa; no fim, reporte o que entrou, onde (as notas criadas) e as relações criadas.

## Modo só conector

Use o modo só conector quando o `brain.py config` sai com 3, ou sai com 0 mas a pasta do vault não está acessível (no celular, no navegador, ou uma pasta bloqueada pelo sistema), ou não há shell, **e** a ferramenta tem um conector do provedor (por exemplo, o do Google Drive) com permissão de criar e ler arquivos. Detalhes, formato da captura e conectores conferidos: `references/connectors.md`.

- **Localizar o vault:** busque pelo conector o arquivo de nome exatamente `brain-config.yml` (pelo nome, não pelo conteúdo); a pasta dele é a raiz do vault, e o arquivo traz o `layout` (como a inbox). Não peça o caminho à pessoa nem comente que a sessão está sem configuração. Com mais de um `brain-config.yml`, use o que tem `index.md` e `log.md` na mesma pasta; só se ainda sobrar mais de um, faça uma pergunta curta sobre qual vault usar.
- **Capturar ("anota isso"):** monte o arquivo com `capture --print`: `brain.py capture "<texto>" --print --json [--context C]` (devolve `path` e `content`; não escreve nada). Sem shell, monte o nome `AAAA-MM-DD-HHMMSS-<slug>.md` e o frontmatter `type: capture` / `created` conforme `references/connectors.md`. Depois, pelo conector, crie um arquivo novo com esse nome e conteúdo em `<vault>/inbox/` (a pasta de `layout.inbox`). Só crie arquivo novo na inbox: nunca sobrescreva — se o nome já existir, gere outro com o `--print` ou acrescente `-1` — e nunca edite, mova ou apague um arquivo do vault pelo conector.
- **Consultar ("o que eu sei sobre X"):** só leitura. Busque e leia as notas pelo conector, responda com base nelas citando `[[nota]]`, e avise que a resposta é parcial (sem o índice e sem os vizinhos por link do `brain.py`); sugira refazer a consulta completa no computador com a pasta. Um arquivo com `confidential: true` no frontmatter não é citado nem resumido.
- **Qualquer outra escrita** (nota organizada, `new-note`, relação, índice, processar a inbox, mover, apagar, `lint`): recuse e explique que isso é feito no computador com a pasta do vault, pelo `brain.py`.
- **Depois, no computador:** "processa minha inbox" segue o fluxo da seção **Capturar e processar a inbox**; as capturas do conector aparecem no `inbox list` como `text`.
- **Sem conector, ou sem permissão:** avise e sugira os outros canais (`references/mobile-capture.md`). A skill nunca pede nem guarda credencial do conector; autorizar o conector é com a pessoa, na ferramenta dela.

## Itens confidenciais e segredos

O segredo (senha, token, chave, PIN) **nunca** entra no vault nem passa por você: fica no gerenciador de senhas da pessoa (KeePass, KeePassXC, Bitwarden, 1Password ou outro). O vault guarda só **onde** ele está, numa nota `secret-ref`. Detalhes, exemplos e as regras do `lint`: `references/confidential.md`.

- **Nunca escreva senha, token ou chave no vault**, em nenhuma nota, nem no texto de um `capture`.
- **Nunca escreva senha, token ou chave na inbox pelo conector** do provedor (modo só conector): o arquivo sincroniza com a nuvem.
- **Quando a pessoa der um segredo:** não guarde o valor; sugira guardá-lo no gerenciador de senhas e ofereça uma nota `secret-ref` que só aponta para ele: `brain.py new-note --type secret-ref --title "Banco" --vault-ref keepass://Pessoal/Banco --json` (`<esquema>://<caminho>`; a skill só valida o formato e nunca abre a referência).
- **Nunca abra o arquivo do gerenciador de senhas** (`.kdbx` e outros), nem peça a senha mestra: quem abre o cofre é a pessoa.
- **Documento pessoal** (RG escaneado, contrato, comprovante): `brain.py ingest ARQ --confidential --context C --json`. O arquivo vai para `files` e nunca passa por processador; a nota de fonte só tem nome, tamanho e hash. Não leia nem resuma o documento.
- **Documento muito sensível:** recomende anexá-lo no próprio gerenciador (o KeePass e o KeePassXC aceitam anexos na entrada) e deixar no vault só a `secret-ref`; o vault no provedor não é cifrado pela pessoa.
- **Fora de vista por padrão:** notas com `confidential: true` (qualquer tipo; `new-note --confidential` grava a marca) ficam fora de `search`, `related`, `context`, `links`, dos MOCs e do `index.md`; a exportação para o NotebookLM nunca as inclui.
- **`--include-confidential` só quando a pessoa pedir**, nesta conversa, para incluir itens confidenciais; nunca por conta própria. O `--json` só diz quantas ficaram fora (`confidential_omitted`): não comente o número se ela não perguntou.
- **No modo só conector, um arquivo com `confidential: true` não é citado nem resumido** pelo conector, mesmo que a busca do provedor o encontre.
- **Achados `secret-in-note` e `personal-data` do `lint`:** mostre o caminho, a linha e o tipo (o `lint` nunca mostra o valor) e proponha tirar o valor da nota (o segredo vai para o gerenciador, com uma `secret-ref`) ou marcar a nota com `confidential: true`; a correção é da pessoa.

## Manter o vault (lint)

Rode a manutenção quando a pessoa pedir ("arruma meu segundo cérebro", "tem link quebrado?"), quando o `brain.py doctor` mostrar a linha `lint` com achados (AVISO ou ERRO), e depois de processar a inbox. O `lint` só lê; a correção é sempre proposta e só acontece com o sim da pessoa. Detalhes de cada regra: `references/maintenance.md`.

1. **Rodar o lint:** `brain.py lint --json` (ou `--only regra,...` para olhar só algumas regras).
2. **Explicar os achados por severidade:** primeiro os erros (`broken-link`, `conflict-copy`, `missing-file`, `config`), depois os avisos (`orphan`, `stale-inbox`, `frontmatter`, `secret-in-note`, `personal-data`), dizendo em palavras simples o que cada um significa.
3. **Propor uma correção por achado:** link quebrado → criar a nota com `new-note` ou corrigir o link; órfã → `relate` com uma nota próxima, ou `index` para pô-la no MOC quando ela tem contexto (o `index` só lista no MOC as notas com contexto), e nas sem contexto `relate` ou uma nota nova que a ligue; cópia de conflito → orientar a pessoa a comparar a cópia com o original e escolher a versão certa ela mesma; inbox parada → o fluxo da inbox; arquivo ausente ou frontmatter → mostrar o que falta.
4. **Aplicar só com o sim do usuário:** cada correção, uma a uma, pelos comandos que só criam e acrescentam (`relate`, `index`, `new-note`); depois rode o `lint` de novo e mostre o resultado.

Nunca apague arquivo: nem a cópia de conflito, nem a nota órfã, nem um item da inbox. Mesclar conflito é decisão da pessoa, feita por ela no Obsidian. O fluxo de guardar continua sendo o único jeito de escrever notas no vault: sempre pelos comandos do `brain.py`, nunca criando arquivos à mão.

## Backup e restauração

O provedor sincroniza também um apagamento ou uma corrupção para todas as máquinas, então o vault precisa de cópias em outros lugares. O `brain.py backup` grava um zip verificado em cada destino configurado. Detalhes, agendamento e restauração: `references/backup.md`.

- **Destinos:** sugira pelo menos dois destinos: um fora do provedor do vault (pasta local ou disco externo) e um em outro provedor ou outra conta. Cadastre cada um com `brain.py backup target add PASTA` (fica só na configuração local desta máquina).
- **Quando rodar:** rode `brain.py backup` antes de uma operação grande (adoção de vault, processar muitos itens da inbox, reorganizar pastas) e quando o `doctor` avisar (`AVISO backup …`: sem backup recente, nenhum backup ou destino inacessível).
- **Restaurar:** sempre com `brain.py restore`, que cria arquivo novo e nunca sobrescreve: uma nota volta como `<nome> (restaurado AAAA-MM-DD).md` ao lado da atual, e o vault inteiro vai para uma pasta nova (`--to`). Mostre as duas versões e deixe a pessoa comparar e escolher; nunca apague nem substitua a nota atual por conta própria.
- **Agendar:** o guia mostra cron, launchd e o Agendador de Tarefas; a skill não instala nada.
- **O zip não é cifrado:** tem o vault inteiro; o destino precisa ser tão protegido quanto o vault.

## Regras

- **`brain.py config` antes de qualquer fluxo.** Configurado → direto ao pedido, sem perguntar configuração. Exit 3 com conector → localize o vault pelo conector e siga no modo só conector, sem perguntar configuração.
- **O vault é do usuário.** O `brain.py` só cria e acrescenta; nada do vault é apagado (a única remoção é a rotação de zips antigos do próprio `backup`, nos destinos de backup, ADR-0015). A única movimentação é tirar da inbox um item já processado (`inbox done`, `ingest --move`). Toda escrita dele no vault aparece no `log.md`.
- **Segredo fora do vault.** Senha, token e chave ficam no gerenciador de senhas; o vault guarda só a `secret-ref` (seção **Itens confidenciais e segredos**).
- **Sem caminho absoluto no vault.** Caminhos de máquina ficam só na configuração local (`references/config.md`).
- **Sem credenciais e sem rede.** A skill só lê e escreve pastas; quem sincroniza é o app do provedor. O conector do provedor, quando usado, é do agente, nunca do `brain.py`, e só cria arquivo novo na inbox e lê notas (modo só conector). Os únicos programas que ela executa são os processadores do `brain-config.yml` (sem shell); o yt-dlp, se configurado, acessa a rede para baixar legendas.
