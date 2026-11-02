# Capturar e consultar pelo conector do provedor

O vault fica numa pasta sincronizada pelo app do provedor (ADR-0008). Quando o agente não enxerga essa pasta — no celular, no navegador, numa máquina sem a pasta montada ou com o acesso bloqueado pelo sistema (no macOS, a proteção de privacidade pode bloquear a pasta do Google Drive) — ele ainda pode usar o **conector do provedor** que a ferramenta dele tiver, por exemplo o conector do Google Drive no app do Claude (ADR-0013, SPEC-0044).

O conector é do agente, nunca do `brain.py`: o `brain.py` continua só com a biblioteca padrão e sem rede (ADR-0007). Ele só monta o arquivo da captura com `capture --print`.

## Quando entra o modo só conector

- o `brain.py config` sai com 3 (não configurado nesta máquina), ou sai com 1 porque o agente não consegue ler o vault (pasta ou `brain-config.yml` inacessível), ou sai com 0 mas a pasta do vault não está acessível, ou não há shell para rodar o `brain.py`; **e**
- a ferramenta tem um conector do provedor do vault com permissão de criar e ler arquivos.

Isso vem antes do onboarding (exit 3) e do `doctor` (exit 1), a menos que a pessoa queira configurar esta máquina (onboarding ou `init --join`) ou consertá-la.

Sem conector, nada muda: valem os canais de `references/mobile-capture.md` e o fluxo normal no computador.

## Regras

1. **Capturar:** pelo conector, o agente só **cria arquivo novo** em `<vault>/<layout.inbox>/` (por padrão `<vault>/inbox/`), no formato da nota de captura abaixo. Nunca sobrescreve: se já existir um arquivo com o nome, gera outro com o `capture --print` (o nome tem segundos) ou acrescenta `-1`, `-2`...
2. **Nunca** edita, move ou apaga um arquivo do vault pelo conector — nem nota, nem item da inbox, nem `index.md` ou `log.md`.
3. **Consultar:** só leitura. Busque e leia as notas pelo conector, responda com base nelas citando `[[nota]]` e avise que a resposta é parcial: sem o índice, sem a pontuação do `search` e sem os vizinhos por link do `related` e do `context`. Sugira refazer a consulta completa no computador com a pasta.
4. **Recusar outras escritas:** nota organizada (`new-note`, `ingest`), relação (`relate`), índice (`index`), processar a inbox (`inbox done`, `ingest --move`) e correções do `lint` são feitas só no computador com a pasta, pelo `brain.py`. Recuse pelo conector e explique isso.
5. **Credenciais:** a autorização do conector fica com a ferramenta do agente. A skill nunca pede nem guarda credencial.

Depois, no computador com a pasta, "processa minha inbox" segue o fluxo de `references/inbox.md`: a captura feita pelo conector aparece no `inbox list` como `text` e sai da inbox com `inbox done`, como qualquer captura.

## Montar a captura

Com shell (o `brain.py` roda, mesmo sem enxergar o vault e mesmo sem configuração):

```text
brain.py capture "<texto>" --print --json [--context C] [--inbox PASTA]
{"path": "inbox/2026-11-02-091500-ideia-sobre-grafos.md", "content": "---\ntype: capture\n..."}
```

- não escreve nada: nem no vault, nem na configuração local, nem no `log.md`;
- com o `brain-config.yml` do vault legível, o caminho usa `layout.inbox` e o contexto é validado (inválido sai com 2);
- sem configuração, ou com o vault, o `brain-config.yml` ou a inbox ausente ou ilegível (o caso da pasta bloqueada pelo macOS), não falha: o caminho usa o `layout.inbox` se ele pôde ser lido, senão `inbox`, ou a pasta do `--inbox` (o nome da pasta da inbox do vault, relativo a ele), e sai com 0;
- `--inbox` com o `brain-config.yml` legível sai com 2: a pasta já é a do `layout.inbox` (`brain.py config` mostra qual é); `--inbox` na raiz do vault (`""`, `.`, `a/..`) ou fora dele (`..`, `a/../../x`, caminho absoluto) sai com 2, conferido sem ler o disco; `--inbox` só vale com `--print`;
- texto vazio sai com 2; sem `--json`, a saída é `<caminho>`, uma linha em branco e o conteúdo.

Crie pelo conector o arquivo `<vault>/<path>` com exatamente o `content`.

Sem shell, monte à mão no mesmo formato.

## Formato da nota de captura

- **Nome:** `AAAA-MM-DD-HHMMSS-<slug>.md` — data e hora locais da captura e o slug das primeiras 6 palavras do texto (minúsculas, sem acento, cada sequência fora de `[a-z0-9]` vira `-`, sem `-` nas pontas, até 60 caracteres; texto sem letras nem dígitos vira `captura`). Ex.: `2026-11-02-091500-ideia-sobre-grafos.md`.
- **Conteúdo:**

```markdown
---
type: capture
created: 2026-11-02T09:15:00
context: college
---

Ideia sobre grafos
```

`type: capture` e `created` (data e hora locais, `AAAA-MM-DDTHH:MM:SS`, o mesmo instante do nome) são obrigatórios; `context` só quando a pessoa disser o contexto. Depois do frontmatter, uma linha em branco e o texto, terminando com uma quebra de linha.

## Como achar o conector de cada provedor

Procure no diretório de conectores (ou de integrações) da ferramenta do agente o conector do provedor onde o vault está, e confira se ele cria arquivos numa pasta escolhida e lê arquivos. A pessoa autoriza o conector na ferramenta dela, com a conta do provedor.

| Provedor | Conector | Conferido |
|---|---|---|
| Google Drive (`google-drive`) | conector "Google Drive" do diretório de conectores do Claude (`drivemcp.googleapis.com`): `create_file` para criar o arquivo novo na inbox, `search_files` para achar notas, `read_file_content` para ler | conferido no diretório de conectores do Claude em 2026-11-02 |
| OneDrive (`onedrive`) | procure um conector do OneDrive / Microsoft 365 na ferramenta | não conferido |
| iCloud (`icloud`) | procure um conector do iCloud Drive na ferramenta | não conferido |
| Outros (pasta local, Dropbox...) | um conector que crie e leia arquivos na pasta do vault | não conferido |

Um conector "não conferido" pode existir ou não, e os nomes das ferramentas dele podem ser outros: confira na ferramenta antes de usar e siga as mesmas regras.

## Limites

- A consulta pelo conector é parcial: sem índice, sem pontuação e sem os vizinhos por link; para uma resposta completa, use o fluxo de consultar no computador (`references/query-flow.md`).
- Só a captura de texto pelo conector segue este formato; arquivos (foto, PDF, vídeo) vão para a inbox pelos canais de `references/mobile-capture.md`.
- Organizar (processar a inbox, `new-note`, `relate`, `index`, `lint`) não é feito pelo conector.
- Sem shell, o nome e o frontmatter são montados pelo agente, que precisa seguir o formato acima à risca.
- Sem conector, ou com o conector sem permissão de criar arquivos, avise a pessoa e sugira os canais de `references/mobile-capture.md`.
