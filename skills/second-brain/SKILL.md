---
name: second-brain
description: >-
  Segundo cérebro num vault do Obsidian mantido junto com uma LLM — notas em Markdown organizadas por PARA, contextos com MOC, inbox, índice e log, num vault sincronizado pelo provedor que a pessoa escolher (Google Drive, OneDrive, iCloud ou pasta local) e usado em várias máquinas e no celular. Use quando o usuário quiser configurar o segundo cérebro (onboarding de vault novo ou existente, ligar uma máquina nova), ver a configuração, criar um contexto, diagnosticar o vault (doctor), buscar notas, notas relacionadas e links (search, related, links) ou guardar qualquer coisa no segundo cérebro — uma anotação, uma aula, um PDF, um vídeo ou um link (ingest, new-note, relate, index). Os fluxos de consultar e manter chegam nas próximas versões.
---

# Second Brain

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
| `doctor [--json]` | Uma linha `OK\|AVISO\|ERRO <item> — <detalhe>` por item; exit 0 sem ERRO, 1 com ERRO, 3 sem configuração |
| `search QUERY [--context C] [--type T] [--tag G] [--limit N] [--json]` | Busca por termos, com pontuação e um trecho de cada nota; sem resultado imprime "Nenhuma nota encontrada para: …" e sai com 0 |
| `related (--note CAMINHO \| --text TEXTO) [--limit N] [--json]` | Notas parecidas com uma nota ou com um texto, cada uma com os motivos; nota inexistente sai com 2 |
| `links NOTA [--json]` | Links de saída (resolvidos ou quebrados) e backlinks de uma nota, pelo caminho ou pelo nome; inexistente sai com 2 |
| `ingest FONTE [--context C] [--title T] [--text-file ARQ] [--json]` | Arquivo: copia para `<files>/<contexto ou inbox>/<AAAA>/` sem sobrescrever (`-1`, `-2`...); URL: nada é copiado. Cria a nota de fonte `raw/AAAA-MM-DD-<slug>.md` com o texto de `--text-file` sob `## Extracted text`. Fonte inexistente sai com 2; pasta `files` inacessível sai com 1 |
| `new-note --type T --title X [--context C] [--source S] [--tags a,b] [--json]` | Cria a nota a partir do modelo do tipo, na pasta do contexto (sem contexto, `resources/`); imprime o caminho. Nota existente, tipo ou contexto inválido saem com 2 |
| `relate DE PARA --why "motivo" [--both]` | Acrescenta `- [[PARA]] — motivo` na seção `## Relations` de DE (e de PARA com `--both`); repetida = "relação já existe" |
| `index [--context C]` | Regenera as regiões geradas dos MOCs (`notes`) e do `index.md` (`contexts`, `recent`), sem tocar no texto da pessoa |

Pontuação e filtros de `search` e `related`: `references/search.md`. Fluxo de guardar em detalhe: `references/store-flow.md`; tipos de nota e frontmatter: `references/note-types.md`. Detalhes das duas camadas de configuração: `references/config.md`. Estrutura do vault: `references/vault-layout.md`. Provedores e celular: `references/providers.md`.

## Antes de qualquer fluxo

Rode sempre `brain.py config` antes de qualquer fluxo, em toda conversa — não confie na memória:

- **Configurado (exit 0)** → siga direto o fluxo pedido, sem perguntar nada de configuração.
- **Exit 3** ("second-brain não configurado nesta máquina") → faça o **onboarding** abaixo, ou o `init --join` se o vault já existir configurado.
- **Exit 1** ou valores estranhos → rode `brain.py doctor` e mostre o resultado antes de seguir.

## Onboarding (exit 3)

Converse com a pessoa; o `brain.py init` não é interativo e recebe tudo por flags.

1. **Provedor:** pergunte onde o vault vai ficar — `google-drive`, `onedrive`, `icloud` ou `local`. Avise sobre o celular conforme `references/providers.md` (ex.: no iPhone, Google Drive e OneDrive não são suportados oficialmente pelo Obsidian; iCloud é o recomendado entre aparelhos Apple; o Obsidian Sync funciona em todos).
2. **Vault novo ou existente:** pergunte se ela já tem um vault.
   - Já tem e ele tem `brain-config.yml` (configurado em outra máquina) → vá para **Máquina nova** abaixo.
   - Já tem, sem `brain-config.yml` → é uma adoção (`--adopt`): pergunte quais pastas ela já usa para inbox, projetos, áreas, recursos e arquivo, e passe cada uma com `--map` (ex.: `--map inbox=Inbox`). Nada existente é movido ou alterado. Se ela já tem um `log.md` ou `index.md` próprio, o `init` sai com 2: passe `--map log=<outro>` (ou `--map index=<outro>`).
   - Não tem → vault novo.
3. **Caminhos:** pergunte onde ficam o vault (dentro da pasta sincronizada do provedor) e a pasta de arquivos pesados (`files`, fora do vault, no mesmo provedor).
4. **Contextos iniciais:** pergunte os assuntos principais (ex.: faculdade, trabalho) e passe cada um com `--context nome=pasta[:título]` (ex.: `--context college=projects/college:College`).
5. **Processadores:** pergunte quais tipos de arquivo ela quer converter em texto (PDF, vídeo...). Registre a resposta; a execução de processadores chega numa versão futura, e o `doctor` já confere se o executável existe no PATH.
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

Para um assunto novo, rode `brain.py context add NOME --folder PASTA --title T` (pasta relativa ao vault). Contexto que já existe sai com 2: não crie outro com o mesmo nome.

## Buscar e relacionar notas

`search`, `related` e `links` só leem o vault (nada é escrito) e não usam rede nem índice: leem as notas a cada execução. Use sempre `--json` para ler os resultados; avisos de notas com frontmatter inválido ou que não são UTF-8 vêm em `warnings` e não impedem o comando — mencione-os à pessoa se forem relevantes.

- **Fluxo de guardar** (seção abaixo; nota nova a partir da inbox, de uma fonte ou de uma conversa): antes de escrever, rode `brain.py related --text "<resumo do conteúdo novo>" --json` e `brain.py search "<termos principais>" --json` para buscar relações. Leia as notas mais bem pontuadas e use os motivos (`tags:`, `mesmo contexto`, `link direto`, `termos:`) para decidir os `[[links]]`, as tags e o contexto da nota nova — e se o conteúdo já existe numa nota que deveria ser complementada em vez de duplicada.
- **Fluxo de consultar** (responder uma pergunta com base no vault): rode `brain.py search "<termos da pergunta>" --json`, filtrando com `--context`, `--type` ou `--tag` quando a pergunta indicar; leia as notas encontradas e rode `brain.py links NOTA --json` para seguir os links de saída e os backlinks até as notas vizinhas. Use `brain.py related --note CAMINHO --json` quando quiser ampliar a partir de uma nota central. Responda citando o caminho de cada nota usada.
- **Links quebrados:** `links` lista em `broken` os alvos que não existem; mostre-os à pessoa, sem criar nem corrigir notas por conta própria.

A busca é por termos (sem acentos e sem diferenciar maiúsculas), não semântica: se nada vier, tente sinônimos e termos mais curtos antes de concluir que o vault não tem a informação.

## Guardar no segundo cérebro

Para guardar qualquer coisa (anotação, aula, PDF, vídeo, link ou o resumo de uma conversa), siga sempre estes seis passos, nesta ordem. Detalhes e exemplos: `references/store-flow.md`.

1. **Classificar:** escolha o tipo (`note`, `lecture`, `source`, `video`, `document`, `link` ou `moc`, conforme `references/note-types.md`) e o contexto. Pergunte o contexto só se for ambíguo; se nenhum servir, sugira criar um com `brain.py context add`.
2. **Guardar o bruto:** arquivo ou link → `brain.py ingest FONTE --context C --json`. Se você consegue ler o arquivo (ou a página), grave o texto num arquivo temporário e passe `--text-file ARQ`; senão a nota de fonte fica com `_(pending)_`. Guarde o caminho `raw` devolvido.
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

## Próximas versões

Os fluxos de **consultar** (respostas com citação das notas), **captura rápida e inbox** e **manter** (lint de links, conflitos de sincronização e órfãs) chegam nas próximas versões da skill. O fluxo de guardar já existe (seção acima) e é o único jeito de escrever notas no vault: sempre pelos comandos do `brain.py`, nunca criando arquivos à mão.

## Regras

- **`brain.py config` antes de qualquer fluxo.** Configurado → direto ao pedido, sem perguntar configuração.
- **O vault é do usuário.** O `brain.py` só cria e acrescenta; nada é apagado. Toda escrita dele no vault aparece no `log.md`.
- **Sem caminho absoluto no vault.** Caminhos de máquina ficam só na configuração local (`references/config.md`).
- **Sem credenciais e sem rede.** A skill só lê e escreve pastas; quem sincroniza é o app do provedor.
