# Modos do atlas: repositório e local

O atlas vive num de dois modos, escolhidos no `init --mode` e gravados em `mode` no `atlas-config.yml`. A skill
detecta e avisa sozinha, mas não roda sozinha (não tem relógio): em cada modo alguém diferente garante que o `scan`
aconteça.

| | Modo `repo` | Modo `local` |
|---|---|---|
| Onde fica | repositório git compartilhado com o time | pasta só desta máquina (com `git init` para ter histórico) |
| Quem roda o `scan` | a CI, agendada (`atlas.py vendor --ci`) | a pessoa, ou um agendamento desta máquina (cron, `/schedule`) |
| Revisão | o PR de scan que a CI abre | o diff local antes do commit |
| Quem avisa que está velho | a própria agenda; `lint` (`stale`) no PR | o aviso de envelhecimento do `context` e o `lint` (`stale`) |

## Modo repositório: `vendor --ci`

```bash
python3 <skill-dir>/scripts/atlas.py vendor --ci github  [--schedule "0 6 * * 1"] [--force]
python3 <skill-dir>/scripts/atlas.py vendor --ci generic [--force]
```

Usa o atlas desta máquina (configuração local, como `scan` e `lint`). Em `mode: local` sai com 2
(`vendor --ci é do modo repo — veja references/modes.md`) sem escrever nada. O `atlas.py` só escreve arquivos: quem
roda git e abre o PR é o workflow (ADR-0010).

### O que é escrito

- **`.org-atlas/skill/`** — cópia da skill (`scripts/atlas.py` e `assets/`: coletores, páginas, modelos), **sempre
  sobrescrita** pelo `vendor`. O workflow e o script rodam `python3 .org-atlas/skill/scripts/atlas.py`, e `{skill}`
  nos `command` dos coletores aponta para essa cópia. Não edite a cópia: rode o `vendor` de novo depois de atualizar a
  skill. O `lint` pula só o `scripts/atlas.py` da cópia (as regex dele parecem segredo), e só quando é idêntico ao
  `atlas.py` da skill que roda o lint; todo o resto da cópia, `assets/**` incluído, é varrido como o resto do atlas,
  inclusive por `secret-leak`. Limitação: quando o `lint` roda da própria cópia (como na CI), não há com o que
  comparar, e uma edição no `atlas.py` da cópia não é varrida; rode o `vendor` de novo para restaurá-lo.
- **`--ci github`** → `.github/workflows/atlas-scan.yml`:
  - `schedule` e `workflow_dispatch`: liga o atlas com `init --join --atlas "$PWD"` e um `ATLAS_CONFIG_HOME`
    temporário fora do atlas (mantém um que já venha definido), roda `scan` e `lint` e, quando a árvore git mudou
    (`git status --porcelain` não vazio), faz commit na branch `atlas/scan-AAAA-MM-DD` e abre o PR com `gh pr create`
    (ou atualiza o PR que já estiver aberto para a branch). Se `lint --only secret-leak` acusar segredo, nada é
    enviado. Coletor falhando: o PR (ou o log, sem mudanças) mostra a falha e o job termina com falha.
  - A branch do dia é do workflow: rodar de novo no mesmo dia a reescreve com `git push --force-with-lease` (só se
    ninguém tiver enviado nada a ela depois do `fetch` do próprio workflow). Não faça commits à mão nessa branch;
    ajuste o atlas noutra branch ou depois do merge.
  - Os secrets de `ci.env` chegam só ao passo `Scan` (os coletores), não aos passos de git e de PR.
  - `pull_request`: roda o `lint` em todo PR do atlas, com `permissions: contents: read`; ERRO falha o job.
  - Permissões do workflow: só `contents: write` e `pull-requests: write`; ações fixadas por SHA.
- **`--ci generic`** → `ci/atlas-scan.sh`, para qualquer outra CI. Rode `bash ci/atlas-scan.sh` na raiz do atlas, com
  git e python3. Saída: **0** sem mudança, **10** com mudança (a CI abre o PR/MR com o diff), **1** com falha
  (coletor, `lint` com ERRO, git).

Arquivo de CI igual ao modelo: `já atualizado`. Diferente (customizado pelo time): mantido, com
`customizado — N linha(s) diferem; use --force para sobrescrever`. Com `--force`: sobrescrito. A cópia da skill é
atualizada nos dois casos. Depois do `vendor`, faça commit de `.org-atlas/` e do arquivo da CI.

### Chave `ci` do `atlas-config.yml`

```yaml
ci:
  env: [GH_TOKEN, ARGOCD_AUTH_TOKEN]   # só nomes; o valor fica nos secrets da plataforma
  schedule: "0 6 * * 1"               # cron em UTC
```

- `env`: os **nomes** das variáveis que os coletores leem. No GitHub, cada nome vira `NOME: ${{ secrets.NOME }}`
  no passo `Scan`: crie no repositório do atlas um secret com o mesmo nome. Na CI genérica, exporte as variáveis com
  esses nomes a partir do cofre da plataforma. Um item fora de `^[A-Z_][A-Z0-9_]*$` (um valor colado, por exemplo)
  faz `config` e `vendor` saírem com 2 e `doctor`/`lint` acusarem ERRO, sem repetir o valor.
- `schedule`: agenda do workflow. Precedência: `vendor --schedule`, senão `ci.schedule`, senão `0 6 * * 1` (segunda,
  06:00 UTC). Mudou a agenda? Rode `vendor --ci github --force` (ou edite o `cron` do workflow).

### Revisão pelo PR

O PR de scan é a revisão do time: o diff mostra o serviço novo, a fila nova, a convenção proposta. Este PR não
confirma convenções (ADR-0012): para confirmar uma, rode `atlas.py curate confirm <id> --by <nome> --via "PR #<n>"`,
que vale quando esse PR for aprovado.

- **PR mesmo sem serviço novo:** cada scan bem-sucedido renova o `seen_at` de cada coletor em
  `snapshots/_scan.json`, então a execução agendada abre (ou atualiza) um PR mesmo quando nenhum serviço mudou. É
  intencional: o merge desse PR mantém a regra `stale` do `lint` e o aviso de envelhecimento do `context` corretos.
- **Token do PR:** o workflow abre o PR com o `github.token`. Um PR criado com esse token **não dispara** os checks
  de `pull_request` (o job `lint` não roda nele), então uma branch protection que exija o `lint` deixa o PR preso; e
  o repositório ou a organização precisa permitir "Allow GitHub Actions to create and approve pull requests"
  (Settings → Actions → General). Alternativa: um token de PAT ou de GitHub App guardado como secret e passado por
  nome — troque `GH_TOKEN: ${{ github.token }}` do passo "Abrir PR com o diff" por `${{ secrets.<NOME> }}` (o
  workflow passa a ser customizado: o `vendor` o mantém e mostra quantas linhas diferem).

## Modo local: agendar nesta máquina

Sem CI, quem garante é o aviso de envelhecimento: o `context` abre com `## Aviso de envelhecimento` e o `lint` acusa
`stale` quando um coletor passou de `stale_days`. Para não depender de lembrar, agende o `scan`:

- **cron** (macOS, Linux), toda segunda às 07:00, com as credenciais disponíveis no ambiente do cron:

  ```cron
  0 7 * * 1  cd /caminho/do/atlas && python3 /caminho/da/skill/scripts/atlas.py scan && python3 /caminho/da/skill/scripts/atlas.py lint
  ```

  O cron não lê o perfil do shell: exporte ali as variáveis de `credentials` (ou carregue-as de um gerenciador de
  segredos), nunca escreva o valor no crontab nem num arquivo versionado.
- **`/schedule`** (agente agendado): peça para rodar `atlas.py scan` e `atlas.py lint` na pasta do atlas e resumir o
  que mudou e os achados.

Revise o diff (`git diff`) e faça commit na pasta do atlas.

## Migração local → repositório

1. Crie o repositório do atlas na plataforma (vazio).
2. Na pasta do atlas: `git remote add origin <url>` e envie a branch principal (`git push -u origin main`).
3. Troque `mode: local` por `mode: repo` no `atlas-config.yml` (é uma linha; não há comando para mudar de modo).
4. Declare `ci.env` (só nomes) e crie os secrets com os mesmos nomes na plataforma.
5. Rode `atlas.py vendor --ci github` (ou `generic`), faça commit de `.org-atlas/` e do arquivo da CI e envie.
6. Nas outras máquinas: clone o repositório e rode `atlas.py init --join --atlas <pasta>`.
7. Remova o agendamento local (cron ou `/schedule`) para não haver dois scans.
