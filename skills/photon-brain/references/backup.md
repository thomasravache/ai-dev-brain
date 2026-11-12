# Backup e restauração do vault

O provedor (Google Drive, OneDrive, iCloud ou outro) sincroniza tudo, inclusive um apagamento, um conflito que vence errado ou uma pasta corrompida: o erro chega a todas as máquinas. O `brain.py` nunca apaga nem sobrescreve nada no vault, mas só um backup em **outro lugar** deixa voltar atrás. A ideia é a regra 3-2-1: três cópias, em dois meios diferentes, uma delas fora do lugar de sempre.

## Escolher os destinos

Um destino é **qualquer pasta** que esta máquina enxerga. Configure pelo menos dois destinos:

- **um fora do provedor do vault:** uma pasta local do computador (fora da pasta sincronizada) ou um disco externo;
- **um em outro provedor ou outra conta:** por exemplo, a pasta sincronizada de outro provedor, ou de outra conta do mesmo provedor. Uma pasta separada na mesma conta também vale, mas protege menos (some junto se a conta tiver problema).

```bash
brain.py backup target add ~/Backups/second-brain             # pasta local, fora do provedor
brain.py backup target add "/Volumes/Disco externo/second-brain"   # disco externo (opcional)
brain.py backup target add "<pasta de outro provedor ou conta>/second-brain-backups"
```

Os destinos ficam só na configuração local desta máquina (`backup_targets`, `references/config.md`): são caminhos desta máquina e nunca vão para o vault. Um destino dentro do vault ou da pasta `files` é recusado (exit 2). Cada máquina pode ter os seus. A mesma pasta escrita de dois jeitos (um link simbólico, outra grafia) conta uma vez: o `target add` responde "destino já existe" e o `backup` grava um zip só nela, também com `--dest` repetido.

## Quando rodar

- Rode `brain.py backup` **antes de uma operação grande**: adotar um vault existente, processar muitos itens da inbox de uma vez, reorganizar pastas ou contextos.
- Rode quando o `doctor` avisar: `AVISO backup <destino> — último há N dia(s), mais que warn_days`, `nenhum backup` ou `inacessível (<motivo>)` (disco desconectado, pasta removida). `AVISO backup — nenhum destino configurado` pede para configurar os destinos.
- No resto do tempo, agende (abaixo).

## O que o backup faz

```bash
brain.py backup [--dest PASTA ...] [--with-files] [--json]
```

- Grava `second-brain-AAAA-MM-DD-HHMMSS.zip` em cada destino (`-files.zip` com `--with-files` ou `backup.with_files: true`). `--dest` substitui os destinos configurados nesta execução.
- O zip tem `vault/<caminho>` de cada arquivo do vault (inclusive `.obsidian/`; um link simbólico que aponta para fora do vault, ou para fora da pasta files, fica fora do zip, porque o conteúdo não é do vault), `files/<caminho>` quando inclui a pasta files, e `brain-backup.json` com a versão, a data e o sha256 de cada entrada. Os caminhos são relativos: nenhum caminho desta máquina vai para o zip. Qualquer descompactador abre o zip, mesmo sem a skill.
- O zip é gravado como `<nome>.partial`, verificado contra o manifesto e só então renomeado. Uma falha no meio nunca substitui nem apaga um backup anterior; o `.partial` daquela tentativa é removido.
- Depois, a **rotação** mantém os `backup.keep` mais recentes (padrão 10) em cada destino, contando separado os zips com e sem `-files`. Ela só apaga zips com o nome do padrão, só depois de verificar o novo, e nunca o novo; qualquer outro arquivo da pasta fica (ADR-0015). Quem quiser um histórico longo copia um zip para outro lugar.
- Um destino que falha (ausente, sem escrita) não impede os outros: o JSON marca `failed` com o motivo e o exit é 1. Nenhum nome é sobrescrito: se o zip daquele segundo já existe, o destino falha com `já existe: <nome>`.
- Um arquivo do vault que não pode ser lido (sem permissão, por exemplo) fica fora do zip e do manifesto, aparece em `skipped` no `--json` e como `AVISO <caminho> — sem leitura` na saída, e o exit é 1; o resto é gravado e verificado normalmente. Corrija a permissão e rode o backup de novo.
- Uma linha vai para o `log.md`: `backup — <nome> → <N> destino(s)`.
- Um `<nome>.partial` que sobra num destino é de um backup interrompido (computador desligado, processo encerrado). O `backup list` e o `doctor` mostram um AVISO para ele, e o `brain.py` nunca o remove sozinho: confira que nenhum backup está rodando e apague o arquivo à mão.

`brain.py backup list` mostra o que existe em cada destino; `brain.py backup verify [ZIP]` confere que o zip abre e bate com o manifesto (sem ZIP: o mais novo de cada destino).

## Restaurar

Restaure sempre com `brain.py restore`, que cria arquivo novo e nunca sobrescreve:

- **Uma nota** (apagada ou alterada por engano): `brain.py restore "projects/college/Aula 1.md" --from <destino>/second-brain-AAAA-MM-DD-HHMMSS.zip` grava `projects/college/Aula 1 (restaurado AAAA-MM-DD).md` ao lado da atual (`-1`, `-2`... se já existir). A nota atual não muda. Mostre as duas versões e deixe a pessoa comparar e escolher; ela decide o que fica e apaga a cópia que não quiser, no Obsidian.
- **O vault inteiro** (pasta corrompida, computador perdido): `brain.py restore --from <zip> --to <pasta nova>` extrai `vault/` (e `files/`) para uma pasta nova ou vazia, fora do vault. Funciona numa máquina ainda sem configuração. Depois a pessoa aponta o vault para lá (`init --join`) ou copia o que precisar.

O `restore` confere o zip antes de gravar: um zip que não verifica, ou com entrada `..` ou caminho absoluto, sai com 1 sem gravar nada. Nunca restaure copiando arquivos do zip por cima do vault.

## Agendar

A skill não instala nada: mostre o exemplo do sistema da pessoa e deixe que ela mesma o configure. Use o caminho completo do `python3` e do `brain.py`.

**cron** (Linux, macOS) — `crontab -e`, todo dia às 21h:

```cron
0 21 * * * /usr/bin/python3 <pasta da skill>/scripts/brain.py backup >> ~/second-brain-backup.log 2>&1
```

**launchd** (macOS) — `~/Library/LaunchAgents/local.second-brain.backup.plist`, carregado com `launchctl load <arquivo>`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.second-brain.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string><pasta da skill>/scripts/brain.py</string>
    <string>backup</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
```

**Agendador de Tarefas** (Task Scheduler, Windows) — no PowerShell:

```powershell
schtasks /Create /SC DAILY /ST 21:00 /TN "second-brain backup" /TR "py <pasta da skill>\scripts\brain.py backup"
```

O agendador roda com o usuário da pessoa: a configuração local (`~/.config/second-brain/config.yml` ou `BRAIN_CONFIG_HOME`) precisa ser a mesma. Um disco externo desconectado faz só aquele destino falhar; o `doctor` mostra quando o último backup ficou velho.

## Segurança

- O zip **não é cifrado** (a skill só usa a biblioteca padrão, sem criptografia própria). Ele tem o vault inteiro, inclusive as notas `confidential: true` (que só guardam referências, nunca o segredo, `references/confidential.md`).
- Por isso o destino precisa ser tão protegido quanto o vault: uma conta com verificação em duas etapas, um disco com a criptografia do sistema (FileVault, BitLocker, LUKS), nunca uma pasta compartilhada com outras pessoas.

## Configuração

```yaml
# brain-config.yml (compartilhado, opcional)
backup:
  keep: 10          # backups mantidos por destino e por tipo (>= 1)
  warn_days: 7      # o doctor avisa quando o último backup é mais velho
  with_files: false # true = inclui a pasta files (pesada)
```

Valor inválido (`keep` < 1, `warn_days` < 0, não inteiro, `with_files` que não é true/false) usa o padrão, com aviso no `config --json` e no `doctor`. Os destinos (`backup_targets`) ficam na configuração local: `references/config.md`.
