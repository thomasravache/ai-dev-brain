---
name: second-brain
description: >-
  Segundo cérebro num vault do Obsidian mantido junto com uma LLM — notas em Markdown organizadas por PARA, contextos com MOC, inbox, índice e log, num vault sincronizado pelo provedor que a pessoa escolher (Google Drive, OneDrive, iCloud ou pasta local) e usado em várias máquinas e no celular. Use quando o usuário quiser configurar o segundo cérebro (onboarding de vault novo ou existente, ligar uma máquina nova), ver a configuração, criar um contexto ou diagnosticar o vault (doctor). Os fluxos de guardar, consultar e manter chegam nas próximas versões.
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

Detalhes das duas camadas de configuração: `references/config.md`. Estrutura do vault: `references/vault-layout.md`. Provedores e celular: `references/providers.md`.

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

## Próximas versões

Os fluxos de **guardar** (inbox, notas sintetizadas, relações, índices), **consultar** (busca e respostas com citação das notas) e **manter** (lint de links, conflitos de sincronização e órfãs) chegam nas próximas versões da skill. Até lá, não escreva notas no vault pelo `brain.py`; se a pessoa pedir, explique que o fluxo ainda não existe.

## Regras

- **`brain.py config` antes de qualquer fluxo.** Configurado → direto ao pedido, sem perguntar configuração.
- **O vault é do usuário.** O `brain.py` só cria e acrescenta; nada é apagado. Toda escrita dele no vault aparece no `log.md`.
- **Sem caminho absoluto no vault.** Caminhos de máquina ficam só na configuração local (`references/config.md`).
- **Sem credenciais e sem rede.** A skill só lê e escreve pastas; quem sincroniza é o app do provedor.
