# Exportar para o NotebookLM (`export-notebooklm`)

O NotebookLM é bom para estudar (resumos em áudio, perguntas guiadas), mas é um silo: o que acontece lá não volta para o vault. Por isso a skill só **gera o pacote**; quem sobe os arquivos é a pessoa. Não há API pública oficial do NotebookLM de consumidor, e a skill não automatiza o navegador (SPEC-0016).

Quando oferecer: a pessoa vai estudar ou se preparar para uma prova ("me prepara para a prova de Cálculo II") → ofereça o pacote do MOC do contexto, além da resposta pelo fluxo de consultar.

## O pacote

`brain.py export-notebooklm MOC --out PASTA [--hops 0..2] [--combined] [--json]`

- `MOC` é o nome do contexto (`college` → `mocs/college.md`) ou o caminho (ou nome) do MOC no vault.
- Entram o MOC, as notas que ele cita e as vizinhas delas por link até `--hops` passos (padrão 1; 0 = só o MOC e as citadas). Como no `context`, o MOC nunca é atravessado, nem os MOCs dos outros contextos (todo MOC de `layout.mocs`), nem o `index.md` e o `log.md`: o que só eles alcançam fica fora. O `index.md` e o `log.md` (`index`, `log`) também não servem de `MOC`: saem com 2 e nada é escrito.
- Em `PASTA` (fora do vault, vazia ou nova) ficam: um `.md` por nota, com o título na primeira linha e sem frontmatter; `sources.md`, com a lista das notas e o caminho de cada uma no vault; e, com `--combined`, `combined.md`, com todas as notas num arquivo só (para quem quer usar poucas fontes).
- Os wikilinks viram texto (`[[Nota|apelido]]` → `apelido`, `[[Nota]]` → `Nota`) e os embeds de anexo viram `(anexo: nome)`: o NotebookLM não segue links nem lê os anexos do vault. Dentro de código (cercas ``` ou ~~~ e código inline) os wikilinks ficam como estão. Um anexo importante (PDF da aula, por exemplo) pode ser subido à parte, direto da pasta `files`.
- O vault não muda (nem o `log.md`). `--out` dentro do vault, ou numa pasta que já tem arquivos, sai com 2 e nada é escrito: o comando nunca sobrescreve. Para exportar de novo, use uma pasta nova. O pacote é gravado numa pasta temporária oculta ao lado de `--out` e movido para lá no final: se a escrita falha no meio (disco cheio, por exemplo), sai com 1, a mensagem diz o motivo e nada fica em `--out`, que continua servindo para uma nova tentativa. Os nomes dos arquivos são comparados como o APFS compara (NFC e sem caixa): dois títulos que só diferem nisso ganham " (2)".

## Passo a passo de envio

1. Gere o pacote: `python3 <skill-dir>/scripts/brain.py export-notebooklm <contexto> --out <pasta nova fora do vault> [--combined]` e mostre à pessoa a lista de arquivos (o `sources.md` diz de onde veio cada nota).
2. No computador, a pessoa abre o NotebookLM (notebooklm.google.com; a ajuda do Google hoje chama o produto de "Gemini Notebook") e abre um notebook dela ou cria um novo.
3. À esquerda, ela seleciona **Add sources** (adicionar fontes) e envia os arquivos `.md` da pasta: um por nota, ou só o `combined.md` se o plano tiver poucas fontes livres no notebook.
4. Ela confere se cada fonte aparece na lista e só então usa o notebook para estudar (resumo em áudio, perguntas).
5. Se algo mudar no vault, gere um pacote novo numa pasta nova e substitua as fontes no notebook; o que for criado no NotebookLM e valer a pena guardar volta para o vault pelo fluxo de guardar.

## Formatos aceitos

Arquivos enviados do computador: Markdown (`.md`), texto (`.txt`), PDF, Microsoft Word (`.docx`), CSV, PowerPoint (`.pptx`), ePub, imagens (png, jpeg, webp, entre outros) e áudio (MP3, WAV, entre outros). Também aceita Google Docs, Google Slides (até 100 slides), Google Sheets (até 100 mil tokens), URLs de sites, vídeos públicos do YouTube e texto colado. O pacote usa só `.md`, que é aceito.

No app de celular a lista é menor; suba o pacote pelo computador.

## Limites

- **Por fonte:** até 500.000 palavras, ou até 200 MB por arquivo enviado. Arquivo acima disso é recusado; nenhuma nota chega perto, mas um `combined.md` de um contexto enorme pode chegar.
- **Fontes por notebook:** 50 fontes no plano gratuito (Standard); 100 no Plus, 300 no Pro, 500 no Ultra (20 TB) e 600 no Ultra (30 TB). Com mais notas do que o limite, use `--combined` (ou `--hops 0`).
- **Notebooks por usuário:** 100 no plano gratuito; 200 no Plus; 500 no Pro e no Ultra.

Os limites mudam com o tempo e o Google avisa que estão sujeitos a mudança: confira de novo se algum número for decisivo.

Formatos e limites conferidos em 2026-10-30 nas páginas oficiais de ajuda do Google:

- https://support.google.com/notebooklm/answer/16215270?hl=en&co=GENIE.Platform%3DDesktop (adicionar fontes, formatos, 500.000 palavras, 200 MB, 50 fontes no gratuito)
- https://support.google.com/notebooklm/answer/16213268?hl=en (fontes e notebooks por plano)
