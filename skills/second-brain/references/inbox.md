# Inbox

O `SKILL.md` define os quatro passos de processar a inbox; aqui estão os detalhes de cada comando. A inbox é a pasta `layout.inbox` do vault (padrão `inbox/`). Nada sai dela apagado: um item processado é **movido** para fora (a única exceção ao "só cria e acrescenta" do ADR-0007), e cada movimentação vira uma linha no `log.md`.

## Exemplo: processar a inbox

```bash
brain.py inbox list --json
# {"items": [{"path": "inbox/aula.pdf", "kind": "file", ...},
#            {"path": "inbox/2026-10-30-140509-ideia-sobre-grafos.md", "kind": "text", ...},
#            {"path": "inbox/.video.mov.icloud", "kind": "syncing", ...}]}
brain.py ingest inbox/aula.pdf --move --context college --json
# {"raw": "raw/2026-10-30-aula.md", "file": "college/2026/aula.pdf", "url": null}  → fluxo de guardar a partir daqui
brain.py new-note --type note --title "Ideia sobre grafos" --context college --json
# {"path": "projects/college/Ideia sobre grafos.md"}  → escreva o corpo, relate e index
brain.py inbox done inbox/2026-10-30-140509-ideia-sobre-grafos.md --note "projects/college/Ideia sobre grafos.md"
# .video.mov.icloud: ainda sincronizando, fica para a próxima vez
```

## `capture TEXTO [--context C] [--json]`

- Cria `inbox/AAAA-MM-DD-HHMMSS-<slug>.md`, com o slug das seis primeiras palavras (minúsculas, sem acentos). Duas capturas com o mesmo nome no mesmo segundo: a segunda ganha `-1`, a terceira `-2`.
- Frontmatter `type: capture`, `created` (data e hora) e `context` (quando dado; precisa existir no `brain-config.yml`), e o texto como corpo.
- Imprime o caminho relativo ao vault (`--json`: `{"path": ...}`); o log ganha `- … capture inbox/<nome>`.
- Texto vazio (ou só espaços) sai com 2 e nada é escrito.

## `inbox list [--json]`

- Um item por arquivo da inbox, inclusive de subpastas, exceto pastas ocultas, arquivos ocultos e metadados do sistema (`.DS_Store`, `Thumbs.db`, `desktop.ini`). O placeholder do iCloud (`.nome.pdf.icloud`) aparece, como `syncing`.
- Ordem: do mais antigo para o mais novo, pela data de modificação do arquivo.
- `kind`:
  - `text`: `.md` ou `.txt`;
  - `link`: `.url`, `.webloc`, ou `.md`/`.txt` cujo texto é só uma URL;
  - `syncing`: placeholder `*.icloud`, ou arquivo de 0 bytes modificado há menos de 10 minutos (o app do provedor ainda está baixando);
  - `file`: todo o resto (PDF, foto, vídeo...).
- `size` em bytes, `age_days` desde a última modificação, `stale` quando `age_days` passa de `inbox_stale_days`, `preview` com até 120 caracteres do texto (`text` e `link`; vazio para `file` e `syncing`).
- Inbox vazia: "Inbox vazia" (exit 0); com `--json`, `{"items": []}`. Só lê: nada é escrito.

## `ingest ITEM --move [...]`

- As mesmas opções e a mesma saída do `ingest` (`references/store-flow.md`), mas o arquivo **sai** da inbox para `<files>/<contexto ou inbox>/<AAAA>/<nome>` em vez de ser copiado, para não deixar arquivo pesado dentro do vault. Nome que já existe em `files` vira `<nome>-1`, `-2`...
- O log ganha duas linhas: `inbox-move inbox/<nome> → <files>/<contexto>/<AAAA>/<nome>` e a do `ingest`.
- Fonte fora da inbox (ou uma URL): exit 2 "--move só vale para itens da inbox", nada muda. Item `syncing`: exit 2 "ainda sincronizando".
- Sem `--move`, o `ingest` de um item da inbox copia e o item fica onde está.

## `inbox done ITEM [--note CAMINHO]`

- Para um item `text` ou `link` já guardado como nota: move para `raw/processed/AAAA-MM/<nome>` (mês de hoje). Nome que já existe lá vira `<nome>-1`, `-2`... e o arquivo existente nunca muda.
- `--note` é a nota criada a partir do item (caminho ou nome, resolvido como um link); o log ganha `- … inbox-done inbox/<nome> → raw/processed/AAAA-MM/<nome> nota: <nota>`.
- Item `file`: exit 2 "arquivo: use ingest --move". Item `syncing`: exit 2 "ainda sincronizando". Item fora da inbox (inclusive `inbox/../raw/x`) ou inexistente: exit 2. Em todo erro o item fica onde estava e o log não muda.

## Itens chegando pelo celular

- Nomes com espaços, acentos, emoji ou parênteses (`Foto 30-10 às 14.05 (1).jpg`) são aceitos como estão; passe o caminho entre aspas.
- O item pode ter sido jogado em outra máquina ou no celular: qualquer máquina com a skill e a configuração local (`init --join`) processa a inbox do mesmo jeito.
- Um item que o app do provedor ainda não baixou aparece como `syncing`: não processe; ele fica para a próxima vez.

## `inbox_stale_days`

Chave de primeiro nível do `brain-config.yml` (padrão 7 quando ausente ou inválida; vaults criados antes funcionam sem mudança). Usada pelo `inbox list` (`stale`) e, quando chegar o fluxo de manter, pelo `lint` (itens parados).
