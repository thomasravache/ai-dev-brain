---
id: ADR-0008
title: Armazenamento do vault e sincronização entre dispositivos
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0017
---

# ADR-0008 — Armazenamento do vault e sincronização entre dispositivos

## Contexto e Problema
O vault precisa ficar na nuvem e ser usado em várias máquinas e no celular (SPEC-0016). A skill é agnóstica: cada pessoa escolhe o provedor no onboarding. A v1 suporta Google Drive, OneDrive, iCloud e pasta local, com celular iOS e Android. Precisamos decidir como a skill acessa o vault e os arquivos pesados, e onde fica a configuração de cada máquina.

## Direcionadores da Decisão
- Um mesmo código para todos os provedores, sem credenciais nem chamada de rede no `brain.py` (ADR-0007).
- O caminho do vault muda de máquina para máquina.
- Vídeos e PDFs grandes deixam a sincronização e a busca lentas se ficarem dentro do vault.
- No celular, o Obsidian só abre o vault em alguns provedores. Segundo a ajuda oficial, iCloud é o recomendado no iOS, e Google Drive e OneDrive não são oficialmente suportados no iOS.

## Opções Consideradas
- **A — Pasta sincronizada pelo app do provedor** (Drive para desktop, OneDrive, iCloud Drive ou qualquer pasta local): a skill só recebe um caminho.
- **B — API de cada provedor** (Google Drive API, Microsoft Graph, CloudKit), com OAuth.
- **C — Plugin do Obsidian** (ex.: Local REST API) como intermediário.

## Resultado da Decisão
**Opção escolhida:** A, porque é a única que trata todos os provedores igual, sem credenciais e sem rede, e funciona com qualquer agente que tenha acesso ao disco.

**Regras (verificáveis):**
- **Configuração compartilhada:** `<vault>/brain-config.yml`, sincronizada com o vault. Guarda estrutura, contextos, processadores e idioma, e nunca caminhos absolutos.
- **Configuração local por máquina:** `$BRAIN_CONFIG_HOME/config.yml` (padrão `~/.config/second-brain/config.yml`). Guarda só `vault`, `files` e `provider` daquela máquina.
- **Arquivos pesados** ficam em `files`, uma pasta fora do vault no mesmo provedor. As notas guardam o caminho relativo a `files`, nunca absoluto.
- `provider` (`google-drive | onedrive | icloud | local`) não muda o comportamento do código. Só escolhe o guia do provedor (`references/providers.md`), os avisos do onboarding sobre o celular e os padrões de cópia de conflito que o `lint` procura.
- Acesso por API dos provedores (para processar a inbox na nuvem, sem pasta montada) fica fora da v1, em spec própria.

### Consequências
- **Boa**, porque trocar de provedor ou de máquina muda só a configuração local, e não há credencial para guardar.
- **Ruim**, porque a skill depende do app de sincronização estar rodando, conflitos de sincronização são possíveis (o `lint` só aponta), e no celular a experiência varia por provedor e sistema.

### Confirmação (G3)
Testes de integração da SPEC-0017: o mesmo vault com duas configurações locais em caminhos diferentes, e `brain-config.yml` sem caminho absoluto. Teste de arquitetura (ADR-0007): nenhuma importação de biblioteca de rede.

## Prós e Contras das Opções
| Critério (peso) | A — pasta sincronizada | B — API dos provedores | C — plugin do Obsidian |
|---|---|---|---|
| Um código para todos os provedores (3) | sim | não (um cliente por provedor) | sim |
| Sem credenciais e sem rede (3) | sim | não | sim (só local) |
| Funciona sem o Obsidian aberto (2) | sim | sim | não |
| Funciona sem pasta montada (sessão na nuvem) (1) | não | sim | não |

## Mais Informações
- https://obsidian.md/help/sync-notes — Obsidian Sync é a opção oficial em todos os sistemas. iCloud é recomendado no iPhone e no iPad, só entre aparelhos Apple. Google Drive e OneDrive não são oficialmente suportados no iOS. No Android, o OneDrive pode não funcionar bem, e a página sugere Dropsync ou FolderSync. Verificado em 2026-10-30.
- SPEC-0016 (decisões do usuário sobre provedores e celular).
