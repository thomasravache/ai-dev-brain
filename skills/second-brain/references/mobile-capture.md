# Capturar pelo celular

No celular não roda a skill: capturar é só **jogar na pasta `inbox/` do vault**. Texto, link, foto, PDF ou vídeo vão pelo menu de compartilhar do sistema para o app do provedor, ou por uma nota rápida no Obsidian mobile. Depois, numa máquina com a skill, "processa minha inbox" faz o resto (`references/inbox.md`).

Tudo o que chega à inbox pelo celular aparece no `inbox list` assim que o app do provedor sincroniza a pasta no computador. Enquanto o arquivo ainda está sendo baixado, ele aparece como `syncing` e não é processado.

**Fonte verificada:** https://obsidian.md/help/sync-notes (verificado em 2026-10-30, ADR-0008). Ela diz:

- o **Obsidian Sync** (pago) é a opção oficial do Obsidian e funciona em todos os sistemas: desktop, iOS e Android;
- o **iCloud** é o recomendado no iPhone e no iPad, só entre aparelhos Apple;
- **Google Drive** e **OneDrive** não são oficialmente suportados no iOS;
- no **Android**, o OneDrive pode não funcionar bem, e a página sugere **Dropsync** ou **FolderSync**.

A fonte trata de abrir o vault no Obsidian, não de salvar arquivos pelo app do provedor. Os passos de compartilhar abaixo são *orientação geral, não verificada*: os nomes dos menus mudam com a versão do app e do sistema; confira no seu aparelho.

## Google Drive (`google-drive`)

- **iOS:** *orientação geral, não verificada* — no item (foto, PDF, página), toque em Compartilhar, escolha o app do Google Drive e, como pasta de destino, a pasta `inbox` do vault. Para texto solto, crie um arquivo de texto e salve na mesma pasta `inbox`.
- **Android:** *orientação geral, não verificada* — no item, toque em Compartilhar, escolha "Salvar no Drive" (app do Google Drive) e selecione a pasta `inbox` do vault.
- **Obsidian mobile:** não é oficialmente suportado no iOS (fonte verificada); a fonte não trata do Google Drive no Android. Para notas rápidas no Obsidian mobile, use o Obsidian Sync.

## OneDrive (`onedrive`)

- **iOS:** *orientação geral, não verificada* — no item, toque em Compartilhar, escolha o app do OneDrive e salve na pasta `inbox` do vault.
- **Android:** *orientação geral, não verificada* — no item, toque em Compartilhar, escolha o OneDrive e selecione a pasta `inbox` do vault como destino do upload.
- **Obsidian mobile:** não é oficialmente suportado no iOS; no Android pode não funcionar bem, e a fonte sugere Dropsync ou FolderSync (fonte verificada). O Obsidian Sync funciona nos dois.

## iCloud (`icloud`)

- **iOS:** *orientação geral, não verificada* — no item, toque em Compartilhar, "Salvar em Arquivos", e escolha iCloud Drive → pasta do vault → `inbox`.
- **Android:** *orientação geral, não verificada* — não há app do iCloud Drive para Android que salve na pasta do vault; a fonte verificada recomenda o iCloud só entre aparelhos Apple. Com Android, a captura pelo celular vai pelo Obsidian Sync (seção **Obsidian mobile**), com a pasta padrão de notas novas na `inbox`.
- **Obsidian mobile:** recomendado no iPhone e no iPad (fonte verificada): abra o vault do iCloud Drive no Obsidian e capture por nota rápida.

## Pasta local (`local`)

- **iOS:** *orientação geral, não verificada* — uma pasta local do computador não chega ao iPhone sozinha, então não há como salvar na `inbox` pelo compartilhar. Use o Obsidian Sync para capturar pelo Obsidian mobile (funciona no iOS, fonte verificada).
- **Android:** *orientação geral, não verificada* — a pasta local também não chega ao Android sozinha. Use o Obsidian Sync (funciona no Android, fonte verificada) ou um app que sincronize a pasta, e salve na `inbox`.
- **Obsidian mobile:** só com o Obsidian Sync (fonte verificada: funciona em todos os sistemas).

## Obsidian mobile

Para capturar com uma nota rápida no Obsidian do celular:

1. Abra o vault no Obsidian mobile. Em quais provedores ele abre o vault (fonte verificada): **iCloud** é o recomendado no iOS (iPhone e iPad, só entre aparelhos Apple); **Google Drive** e **OneDrive** não são oficialmente suportados no iOS; no **Android**, o OneDrive pode não funcionar bem (a fonte sugere Dropsync ou FolderSync); o **Obsidian Sync** funciona em todos, iOS e Android.
2. Defina a pasta padrão de notas novas como `inbox`: *orientação geral, não verificada* — em Configurações → Arquivos e links → "Local padrão para novas notas", escolha a pasta `inbox` (ou o nome de `layout.inbox` do seu `brain-config.yml`). Assim toda nota nova criada no celular cai na inbox.
3. Escreva a ideia como uma nota nova; colar só um link também vale (aparece como `link` no `inbox list`).

A configuração do Obsidian fica em `.obsidian/`, dentro do vault; se ela sincroniza entre os aparelhos, depende do provedor e do Obsidian Sync (*orientação geral, não verificada*): confira a pasta de notas novas em cada aparelho.
