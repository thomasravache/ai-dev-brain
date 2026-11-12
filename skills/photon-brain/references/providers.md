# Provedores e celular

A skill não instala nem configura o app de sincronização: ela só recebe o caminho da pasta. Escolha o provedor no onboarding (`--provider`) e siga a seção dele. O `provider` não muda o código; muda o guia e os avisos do `doctor`.

**Fonte verificada:** https://obsidian.md/help/sync-notes (verificado em 2026-10-30, ADR-0008). Ela diz:

- o **Obsidian Sync** (pago) é a opção oficial do Obsidian e funciona em todos os sistemas: desktop, iOS e Android;
- o **iCloud** é o recomendado no iPhone e no iPad, só entre aparelhos Apple;
- **Google Drive** e **OneDrive** não são oficialmente suportados no iOS;
- no **Android**, o OneDrive pode não funcionar bem, e a página sugere **Dropsync** ou **FolderSync**.

O que não está nessa lista vem marcado como *orientação geral, não verificada*: confira na documentação do provedor antes de seguir.

## Google Drive (`google-drive`)

- **Desktop:** *orientação geral, não verificada* — instale o app de desktop do Google Drive, crie o vault dentro da pasta sincronizada e deixe o vault e a pasta `files` disponíveis offline.
- **iOS:** o Google Drive não é oficialmente suportado pelo Obsidian no iPhone e no iPad (fonte verificada). Para usar o vault no celular, use o Obsidian Sync.
- **Android:** a fonte verificada não trata do Google Drive no Android. O Obsidian Sync funciona no Android (fonte verificada).

## OneDrive (`onedrive`)

- **Desktop:** *orientação geral, não verificada* — instale o app do OneDrive, crie o vault dentro da pasta dele e deixe o vault e a pasta `files` sempre disponíveis no dispositivo.
- **iOS:** o OneDrive não é oficialmente suportado pelo Obsidian no iPhone e no iPad (fonte verificada); use o Obsidian Sync.
- **Android:** o OneDrive pode não funcionar bem com o Obsidian; a fonte verificada sugere Dropsync ou FolderSync, e o Obsidian Sync também funciona.

## iCloud (`icloud`)

- **Desktop:** *orientação geral, não verificada* — no Mac, crie o vault no iCloud Drive para que os aparelhos Apple vejam a mesma pasta.
- **iOS:** recomendado no iPhone e no iPad, entre aparelhos Apple (fonte verificada).
- **Android:** a fonte verificada recomenda o iCloud só entre aparelhos Apple; com Android, use o Obsidian Sync, que funciona em todos.

## Pasta local (`local`)

- **Desktop:** qualquer pasta do disco; a skill trata como pasta comum. Se outro programa sincroniza essa pasta, a skill não sabe nem depende disso.
- **iOS:** *orientação geral, não verificada* — uma pasta local do computador não chega ao iPhone sozinha. O Obsidian Sync funciona no iOS (fonte verificada).
- **Android:** *orientação geral, não verificada* — a pasta local também não chega ao Android sozinha. O Obsidian Sync funciona no Android (fonte verificada).

## Cópias de conflito (`conflict_patterns`)

Quando duas máquinas (ou o celular) mudam a mesma nota antes de sincronizar, o app do provedor pode guardar as duas versões, com um sufixo no nome da cópia. O `brain.py lint` aponta essas cópias com a regra `conflict-copy` (erro), mas só quando o original (`<base>.md`) existe na mesma pasta. A skill nunca mescla nem apaga a cópia: quem compara e escolhe é a pessoa (`references/maintenance.md`).

Sem `conflict_patterns` no `brain-config.yml`, valem os padrões do `provider` da configuração local desta máquina, abaixo. Cada padrão é um regex sobre o nome do arquivo, com o grupo `base` (o nome do original sem `.md`).

| Provedor | Padrões da v1 | Conferência |
|---|---|---|
| Google Drive (`google-drive`) | `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` | padrão genérico; nomes reais do provedor não conferidos nesta máquina em 2026-10-30 |
| OneDrive (`onedrive`) | `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` | padrão genérico; nomes reais do provedor não conferidos nesta máquina em 2026-10-30 |
| iCloud (`icloud`) | `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` | padrão genérico; nomes reais do provedor não conferidos nesta máquina em 2026-10-30 |
| Pasta local (`local`) | `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` | padrão genérico (vale para outro programa que sincronize a pasta); nomes reais não conferidos nesta máquina em 2026-10-30 |

Os quatro provedores usam, por enquanto, os mesmos padrões genéricos: `Aula (1).md` (número entre parênteses) e `Plano conflict 2026-10-30.md` (a palavra `conflict`, em qualquer caixa, depois de espaço, `_` ou `-`). Os nomes que cada app grava de verdade não foram conferidos com cópias reais nesta máquina; se o seu provedor usa outro formato, ponha o padrão em `conflict_patterns` no `brain-config.yml` (ele sincroniza e vale para todas as máquinas):

```yaml
conflict_patterns:
  - '(?P<base>.+) \(\d+\)\.md$'
  - '(?i)(?P<base>.+)[ _-]conflict.*\.md$'
```

Regex inválido, ou sem o grupo `base`, vira um achado `config` (erro) no `lint`; os outros padrões e as outras regras continuam rodando. Um padrão com quantificador aninhado (`(a+)+`, `(a*)*`, `(a+)*`, `(?:a+)+`, `(\w+\s?)+`, `(a+){20}`, `(a*){2,5}` e variações) ou com mais de 500 caracteres também vira um achado `config` e nunca é usado: um padrão assim pode travar o `lint` e o `doctor` em todas as máquinas, porque o `brain-config.yml` sincroniza. A verificação é de melhor esforço: alternativas sobrepostas, como `(a|aa)+`, não são detectadas. Prefira padrões simples (um `.+` para o nome e o sufixo literal da cópia).
