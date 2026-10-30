# Provedores e celular

A skill não instala nem configura o app de sincronização: ela só recebe o caminho da pasta. Escolha o provedor no onboarding (`--provider`) e siga a seção dele. O `provider` não muda o código; muda o guia e os avisos do `doctor`.

Em todos os provedores, o **Obsidian Sync** (pago) é a opção oficial do Obsidian e funciona no desktop, no iOS e no Android. Fonte: https://obsidian.md/help/sync-notes (verificado em 2026-10-30).

## Google Drive (`google-drive`)

- **Desktop:** instale o Google Drive para desktop e crie o vault dentro da pasta sincronizada (no macOS fica em `~/Library/CloudStorage/GoogleDrive-<conta>/`). Marque o vault e a pasta `files` como disponíveis offline.
- **iOS:** o Obsidian não suporta oficialmente o Google Drive no iPhone e no iPad. Para usar o vault no celular, use o Obsidian Sync.
- **Android:** não há sincronização oficial do Google Drive com o Obsidian; use o Obsidian Sync ou um app de sincronização de pastas.

## OneDrive (`onedrive`)

- **Desktop:** instale o OneDrive e crie o vault dentro da pasta dele; deixe o vault e a pasta `files` sempre disponíveis neste dispositivo.
- **iOS:** o Obsidian não suporta oficialmente o OneDrive no iPhone e no iPad; use o Obsidian Sync.
- **Android:** o OneDrive pode não funcionar bem com o Obsidian; a ajuda oficial sugere Dropsync ou FolderSync para manter a pasta sincronizada, ou o Obsidian Sync.

## iCloud (`icloud`)

- **Desktop:** no Mac, crie o vault em iCloud Drive (`~/Library/Mobile Documents/iCloud~md~obsidian/Documents/` aparece para o iPhone). No Windows, use o iCloud para Windows.
- **iOS:** recomendado no iPhone e no iPad, entre aparelhos Apple: crie o vault pelo Obsidian no iOS marcando "Store in iCloud" e abra a mesma pasta no Mac.
- **Android:** o iCloud não sincroniza com o Android; quem usa Android precisa do Obsidian Sync ou de outro provedor.

## Pasta local (`local`)

- **Desktop:** qualquer pasta do disco, ou uma sincronizada por outro meio (Syncthing, Dropbox, git). A skill trata como pasta comum.
- **iOS:** uma pasta local do computador não chega ao iPhone sozinha; use o Obsidian Sync ou mova o vault para o iCloud.
- **Android:** use o Obsidian Sync ou um app de sincronização de pastas (ex.: Syncthing, FolderSync).
