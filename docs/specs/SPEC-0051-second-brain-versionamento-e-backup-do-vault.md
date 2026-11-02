---
id: SPEC-0051
title: "second-brain: versionamento e backup do vault"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-02
parent:
depends_on: [SPEC-0017]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/backup.md, skills/second-brain/references/config.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008, ADR-0015]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-02
---

# SPEC-0051 — second-brain: versionamento e backup do vault

## 1. Visão Geral
Hoje o segundo cérebro **evita** perder dados (o `brain.py` nunca apaga nem sobrescreve, as escritas são atômicas e tudo vai para o `log.md`), mas não tem **como voltar atrás**. Nada protege contra:
- um erro da pessoa ou de outro programa (apagar uma nota no Obsidian);
- um conflito de sincronização que vence errado, replicado pelo provedor para todas as máquinas;
- uma pasta corrompida, um computador perdido ou um problema na conta do provedor.

A spec dá ao vault cópias restauráveis em **vários destinos** (a regra 3-2-1: três cópias, em dois meios diferentes, uma delas fora do lugar de sempre), sem depender de nenhum provedor:
- `brain.py backup` grava um `.zip` datado e verificado do vault em cada destino configurado: uma pasta local fora do provedor, uma pasta de outro provedor ou conta, um disco externo. Qualquer pasta serve.
- A rotação mantém os N mais recentes em cada destino (padrão 10) e só apaga zips criados pelo próprio `backup` (ADR-0015).
- `backup verify` prova que um zip abre e confere com o manifesto. `backup list` mostra o que existe.
- `restore` nunca sobrescreve: recupera uma nota como arquivo novo ao lado da atual, ou o vault inteiro numa pasta nova.
- O `doctor` avisa quando um destino está sem backup recente ou inacessível.

## 2. Motivação & Escopo
**Motivação:** a pessoa quer garantir que não aconteça nenhuma perda de dados. O vault é sincronizado pelo provedor, e a sincronização replica um apagamento ou uma corrupção para todas as máquinas. Um backup só no mesmo provedor se perde junto, por isso os destinos são vários e escolhidos pela pessoa.

**Objetivos:**
- `backup` (um zip por destino, atômico, verificado, com rotação), `backup list`, `backup verify`, `backup target add`.
- `restore NOTA --from ZIP` (arquivo novo ao lado da nota) e `restore --from ZIP --to PASTA` (vault inteiro numa pasta nova).
- Configuração: destinos na configuração local (`backup_targets`, porque são caminhos desta máquina) e `backup.keep`, `backup.warn_days` e `backup.with_files` no `brain-config.yml`.
- `doctor`: idade do último backup em cada destino.
- `SKILL.md` e `references/backup.md`: quando fazer backup, como escolher os destinos (um fora do provedor e um em outro provedor ou conta), como agendar com o agendador do sistema e como restaurar.

**Não-objetivos:**
- Backup pela API de um provedor (ADR-0008): o destino é sempre uma pasta.
- Histórico fino com git dentro do vault (fica para depois, como guia opcional).
- Agendar o backup sozinho: o guia mostra como, mas a skill não instala nada.
- Criptografar o zip (só biblioteca padrão, sem cripto própria). O guia avisa que o destino precisa ser tão protegido quanto o vault.

## 3. Dependências
- **Implementações necessárias:** SPEC-0017 (configuração em duas camadas e `doctor`), já implementada.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** nenhum (`zipfile` e `hashlib` são da biblioteca padrão).

## 4. Decisão Arquitetural
**Contexto:** projeto existente; segue o ADR-0007 (só biblioteca padrão, sem rede, nunca apaga nem sobrescreve no vault) e o ADR-0008 (pastas, sem API, configuração em duas camadas).

**Decisão:** um zip da biblioteca padrão por destino, com manifesto de hashes. A rotação é a **única remoção** que o `brain.py` faz, fora do vault e da pasta `files`, só de nomes que ele mesmo cria e só depois de verificar o zip novo (ADR-0015, que completa o ADR-0007).

**Referência de implementação:**
- configuração local e compartilhada: `read_config`, `LOCAL_KEYS`, `SHARED_KEYS` e o tratamento de valor inválido de `inbox_stale_days` (SPEC-0017, SPEC-0021);
- escrita atômica e sem sobrescrever: `create_file` e `write_new_file`;
- pasta nova e vazia fora do vault: `export_folder` e `export_staging` (SPEC-0024);
- linhas do `doctor`: `doctor_items` e `processor_items`.

**Justificativa:** o zip funciona igual em qualquer provedor, sistema e agente, e a pessoa abre um backup com o descompactador do sistema mesmo sem a skill.

**Desvio do padrão existente:** a rotação apaga arquivos fora do vault. Isso está coberto pelo ADR-0015 e guardado por teste de arquitetura.

**Alternativas descartadas:** depender só do histórico de versões do provedor (diferente em cada um, e some junto com a conta); o `brain.py` executar git (processo externo fora dos processadores, ADR-0007); backup incremental próprio (mais complexo, e restaurar sem a skill fica difícil).

**ADRs:** ADR-0007 e ADR-0008 (aplicados); ADR-0015 (novo).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** medido uma vez na entrega (vault de 5.000 notas), sem teste de tempo novo, para não repetir os testes que falham com a máquina carregada.
- **Segurança:** o `restore` recusa entradas do zip com `..` ou caminho absoluto (IT-07). O zip contém o vault inteiro, inclusive as notas confidenciais (que só têm referências, SPEC-0050), e o guia avisa que o destino precisa ser tão protegido quanto o vault.
- **Privacidade e dados pessoais:** os destinos ficam só na configuração local da pessoa, nunca no repositório nem no vault.
- **Disponibilidade e resiliência:** o zip é gravado como `.partial` e renomeado só depois de verificado, então um backup que falha no meio não substitui nem apaga o anterior (IT-03). Um destino que falha não impede os outros (IT-02).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** espaço nos destinos, controlado por `backup.keep` e por `with_files` desligado por padrão.

## 6. Artefato A — Contrato
**Interface:**

```text
Configuração local ($BRAIN_CONFIG_HOME/config.yml):
  backup_targets: ["<pasta 1>", "<pasta 2>"]      # caminhos desta máquina
brain-config.yml (opcional):
  backup: {keep: 10, warn_days: 7, with_files: false}
  keep < 1 ou warn_days < 0 ou não inteiro → usa o padrão, com aviso (como inbox_stale_days)

brain.py backup target add PASTA
  → acrescenta PASTA (absoluta) a backup_targets; repetida = "destino já existe", exit 0
  PASTA dentro do vault ou da pasta files → exit 2

brain.py backup [--dest PASTA ...] [--with-files] [--json]
  → um zip por destino (--dest substitui backup_targets nesta execução):
      second-brain-AAAA-MM-DD-HHMMSS.zip          (só o vault)
      second-brain-AAAA-MM-DD-HHMMSS-files.zip    (com --with-files ou backup.with_files: true)
  → conteúdo: vault/<caminho> de cada arquivo do vault, files/<caminho> com files, e brain-backup.json:
      {"brain_version", "created", "with_files", "entries": {"<caminho no zip>": "<sha256>"}}
  → grava <nome>.partial, verifica, renomeia; depois rotação no destino (ADR-0015)
  → linha no log.md: "backup — <nome> → <N> destino(s)"
  → --json: {"name", "entries", "targets": [{"path", "status": "ok"|"failed", "detail", "removed": [nomes]}]}
  sem destino configurado nem --dest           → exit 2 ("nenhum destino de backup — references/backup.md")
  destino dentro do vault ou da pasta files    → exit 2, nada gravado
  destino ausente ou sem escrita               → aquele destino falha, os outros seguem; exit 1
  todos os destinos ok                         → exit 0

brain.py backup list [--json]
  → por destino, do mais novo para o mais velho: nome, data, tamanho, número de entradas, with_files
  destino inacessível → aparece com o motivo; exit 0

brain.py backup verify [ZIP] [--json]
  → sem ZIP: o mais novo de cada destino; confere que o zip abre, que cada entrada do manifesto existe e bate com o sha256
  → "OK <zip> — N entradas" ou "ERRO <zip> — <motivo>"; exit 0 sem erro, 1 com erro, 2 com ZIP inexistente

brain.py restore NOTA --from ZIP [--json]
  → NOTA = caminho relativo ao vault; grava "<pasta>/<nome> (restaurado AAAA-MM-DD).md" no vault (-1, -2... se existir)
  → nunca sobrescreve a nota atual; linha no log.md
  NOTA fora do zip → exit 2; zip que não verifica → exit 1, nada gravado

brain.py restore --from ZIP --to PASTA [--json]
  → extrai vault/ (e files/, se houver) para PASTA nova ou vazia
  PASTA com arquivos, dentro do vault ou da pasta files → exit 2
  entrada com ".." ou caminho absoluto → exit 1, nada gravado

doctor, por destino:
  OK backup <destino> — último há N dia(s) (<nome>)
  AVISO backup <destino> — último há N dia(s), mais que warn_days | nenhum backup | inacessível (<motivo>)
  AVISO backup — nenhum destino configurado (references/backup.md)
```

**Instruções do agente (`SKILL.md` e `references/backup.md`):**
- sugerir pelo menos dois destinos: um fora do provedor do vault (pasta local ou disco externo) e um em outro provedor ou outra conta;
- rodar `backup` antes de uma operação grande (adoção, processar muitos itens da inbox) e quando o `doctor` avisar;
- restaurar sempre com `restore`, que cria arquivo novo, e deixar a pessoa comparar e escolher;
- mostrar como agendar com o agendador do sistema (cron, launchd, Agendador de Tarefas), sem instalar nada;
- avisar que o zip não é cifrado e que o destino precisa ser tão protegido quanto o vault.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Configuração do backup | `backup` com valores válidos, ausentes e inválidos | padrão 10/7/false, aviso para inválido | UT-01 |
| Nome e rotação | lista de nomes no destino, `keep` | só os nomes do padrão contam, os mais velhos além de `keep` saem, outros arquivos ficam | UT-02 |
| Manifesto | vault pequeno | entradas `vault/...` com sha256 corretos | UT-03 |
| Verificação | zip íntegro, entrada alterada, entrada faltando, zip truncado | OK só para o íntegro, motivo para os outros | UT-04, IT-04 |
| Entrada perigosa | `../x` ou caminho absoluto no zip | recusada | UT-05, IT-07 |
| Adicionar destino | `backup target add` nova, repetida, dentro do vault | grava, "destino já existe", exit 2 | IT-01 |
| Backup em dois destinos | dois destinos válidos | um zip verificado em cada, linha no log, exit 0 | IT-02 |
| Destino que falha | um destino ausente e um válido | o válido recebe o zip, exit 1, detalhe do que falhou | IT-02 |
| Sem destino | nada configurado e sem `--dest` | exit 2 com a referência | IT-02 |
| Destino proibido | `--dest` dentro do vault ou da pasta files | exit 2, nada gravado | IT-02 |
| Falha no meio | escrita falha depois de começar | sem `.partial` renomeado, backups anteriores intactos | IT-03 |
| Rotação real | 11 backups e `keep: 10`, mais um arquivo da pessoa no destino | sobram 10 do padrão, o arquivo da pessoa fica | IT-03 |
| Com files | `--with-files` | nome `-files.zip`, entradas `files/...` | IT-02 |
| Listar | dois destinos, um inacessível | lista por destino, motivo do inacessível, exit 0 | IT-04 |
| Restaurar nota | nota apagada ou alterada depois do backup | arquivo novo `(restaurado AAAA-MM-DD)`, a atual intacta, linha no log | IT-05 |
| Restaurar nota inexistente | NOTA fora do zip | exit 2 | IT-05 |
| Restaurar tudo | `--to` pasta nova | vault (e files) extraídos; pasta com arquivos ou dentro do vault, exit 2 | IT-06 |
| Doctor | destino com backup recente, velho, sem backup, inacessível, nenhum destino | uma linha OK ou AVISO por caso | IT-08 |
| Instruções | `SKILL.md` e `references/backup.md` | destinos, quando rodar, restaurar, agendar, aviso de cifra | UT-06 |
| Remoção só na rotação | código do `brain.py` | apagar arquivo só em `rotate_backups` e na lista fechada de limpezas do que a própria chamada criou | UT-07 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — nenhum comando existente muda; os testes do `doctor` e da configuração continuam valendo.

### 7.2 Testes Unitários
- **UT-01** — Dado `backup` ausente, `{keep: 3, warn_days: 0, with_files: true}`, `{keep: 0}`, `{keep: "x"}` e `{warn_days: -1}`, quando a configuração é lida, então os válidos são usados, os ausentes viram 10, 7 e false, e os inválidos usam o padrão com um aviso que cita a chave.
- **UT-02** — Dado os nomes `second-brain-2026-11-01-080000.zip` a `…-11-12-…`, `second-brain-2026-11-12-080000-files.zip`, `notas.zip`, `second-brain-x.zip` e um `.partial`, quando a rotação calcula o que sai com `keep: 10`, então saem só os dois mais velhos sem `-files`, e o `-files`, `notas.zip`, `second-brain-x.zip` e o `.partial` ficam.
- **UT-03** — Dado um vault com três arquivos (um em subpasta e um em `.obsidian/`), quando o manifesto é montado, então tem `vault/<caminho>` de cada um com o sha256 certo, `with_files: false` e a `brain_version`.
- **UT-04** — Dado um zip íntegro, um com uma entrada alterada, um sem uma entrada do manifesto e um truncado, quando verificados, então só o primeiro passa, e os outros trazem o motivo (hash diferente, entrada faltando, zip inválido).
- **UT-05** — Dado entradas `vault/a.md`, `vault/../x.md`, `/etc/x` e `vault/sub/../../x.md`, quando checadas para extração, então só a primeira é aceita.
- **UT-06** — Dado `SKILL.md` e `references/backup.md`, quando lidos, então trazem: pelo menos dois destinos, um fora do provedor e outro em outro provedor ou conta; rodar antes de operação grande e quando o `doctor` avisar; restaurar com `restore`, que cria arquivo novo; agendar pelo agendador do sistema, sem instalar nada; e o aviso de que o zip não é cifrado.
- **UT-07** — Dado o código de `skills/second-brain/scripts/brain.py`, quando o teste de arquitetura do ADR-0015 analisa as chamadas, então `os.remove`, `os.unlink`, `Path.unlink`, `os.rmdir`, `Path.rmdir` e `shutil.rmtree` só aparecem dentro de `rotate_backups` e das funções de limpeza já existentes, numa lista fechada (`write_export`, `copy_to_files` e `move_out_of_inbox`, que só removem o que a própria chamada criou); uma remoção em qualquer outra função reprova o teste.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init`, quando roda `backup target add <pasta>` duas vezes e com uma pasta dentro do vault, então a configuração local tem a pasta uma vez, a segunda chamada diz "destino já existe" com exit 0, e a terceira sai com 2 sem mudar a configuração.
- **IT-02** — Dado dois destinos configurados, quando roda `backup --json`, então cada destino tem um zip que passa no `backup verify`, o `log.md` tem a linha do backup e o exit é 0; com um dos destinos removido, o outro recebe o zip, o JSON marca `failed` com o motivo e o exit é 1; sem destino, sai com 2; com `--dest` dentro do vault ou da pasta files, sai com 2 sem gravar; com `--with-files`, o nome termina em `-files.zip` e há entradas `files/...`.
- **IT-03** — Dado um destino com 11 backups do padrão e um `fotos.zip` da pessoa, e `keep: 10`, quando roda `backup`, então sobram 10 backups do padrão (o novo entre eles), o `fotos.zip` fica, e o JSON lista os removidos; e, dado uma falha de escrita simulada no meio do zip, os backups anteriores ficam intactos, nenhum nome do padrão é criado e o exit é 1.
- **IT-04** — Dado dois destinos, um com dois backups e outro inacessível, quando roda `backup list --json` e `backup verify`, então a lista traz os dois backups do mais novo para o mais velho e o motivo do destino inacessível, com exit 0, e o `verify` diz OK para o mais novo; com um zip alterado à mão, o `verify` diz ERRO e sai com 1; com um ZIP inexistente, sai com 2.
- **IT-05** — Dado um backup e, depois dele, uma nota alterada e outra apagada, quando roda `restore <nota alterada> --from ZIP` e `restore <nota apagada> --from ZIP`, então surgem `<nome> (restaurado AAAA-MM-DD).md` com o conteúdo do backup, a nota alterada não muda, a segunda restauração da mesma nota cria `-1`, e o `log.md` tem as linhas; com uma nota que não está no zip, sai com 2.
- **IT-06** — Dado um backup com files, quando roda `restore --from ZIP --to <pasta nova>`, então a pasta tem `vault/` e `files/` iguais aos do backup; com uma pasta que já tem arquivos, ou dentro do vault, sai com 2 sem gravar.
- **IT-07** — Dado um zip montado à mão com uma entrada `vault/../fora.md` e um manifesto coerente, quando roda `restore --from ZIP --to <pasta nova>`, então sai com 1, nada é gravado e `fora.md` não existe fora da pasta.
- **IT-08** — Dado destinos com backup de hoje, com backup de 10 dias atrás (`warn_days: 7`), sem backup e inacessível, e uma configuração sem destinos, quando roda `doctor`, então há uma linha `OK backup` para o primeiro e `AVISO backup` com o motivo para cada um dos outros, e, sem destinos, `AVISO backup — nenhum destino configurado`.

### 7.4 Testes de Contrato
- N/A — sem contrato entre specs.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração.

### 7.6 Outros
- **Arquitetura (G3):** o UT-07 roda junto com o teste de arquitetura do ADR-0015.

**Dublês e dados de teste:** vaults, destinos e configurações temporários com `HOME` e `BRAIN_CONFIG_HOME` isolados; relógio injetável para os nomes e as idades; zips montados à mão para os casos inválidos; falha de escrita simulada substituindo a escrita do zip no teste.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto. Sem destino configurado, nada acontece além do AVISO do `doctor`.
- **Dados/schema:** chaves novas e opcionais (`backup_targets` na configuração local, `backup` no `brain-config.yml`).
- **Compatibilidade:** nenhum comando existente muda.
- **Observabilidade:** as linhas `backup` do `doctor` e a linha de cada backup no `log.md`.
- **Rollback:** `git revert` do merge. Os zips já criados continuam válidos e abrem com qualquer descompactador.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde os backups devem ficar: outra pasta sincronizada (ex.: outra conta ou provedor), um disco externo, ou os dois? (thomas) — vários destinos (`backup_targets`), qualquer pasta: uma local fora do provedor do vault e uma na cloud, de preferência outro provedor ou conta (uma pasta separada no mesmo provedor também vale, protegendo menos); disco externo opcional (thomas, 2026-11-02)
- [x] Quer histórico fino das notas (git dentro do vault, com o guia) além dos backups zip, ou só os backups? (thomas) — por enquanto só os zips; o git fica como guia opcional para depois (thomas, 2026-11-02)
- [x] A rotação pode apagar backups antigos na pasta de backups (fora do vault)? Quantos manter? (thomas) — sim, mantendo os 10 mais recentes por destino (`backup.keep`), só zips criados pelo `backup` e só depois de verificar o novo; registrado no ADR-0015 (thomas, 2026-11-02)
- [x] O backup inclui a pasta `files/` (vídeos e PDFs, pesada) ou só as notas? (thomas) — só o vault por padrão; `--with-files` ou `backup.with_files: true` incluem a pasta files (thomas, 2026-11-02)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Configuração, manifesto e rotação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05 e UT-07 com a tag `SPEC-0051:<ID>`, falhando pelo motivo certo
- [ ] Green: leitura de `backup`, manifesto sha256, verificação, checagem de entradas e `rotate_backups`
- [ ] Refactor mantendo tudo verde

**Fase 2: Comandos backup e restore**
- [ ] Red: IT-01 a IT-07 falhando pelo motivo certo
- [ ] Green: `backup target add`, `backup` (.partial → verificado → renomeado → rotação), `backup list`, `backup verify`, `restore NOTA` e `restore --to`
- [ ] Refactor mantendo tudo verde

**Fase 3: Doctor e instruções**
- [ ] Red: IT-08 e UT-06 falhando pelo motivo certo
- [ ] Green: linhas `backup` do `doctor`, `SKILL.md`, `references/backup.md` e `references/config.md`
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 29b2dc6 (árvore suja) | 2026-11-02 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-02 | G1 | spec | UT-07 e ADR-0015 exigem remoção de arquivo só em rotate_backups, mas o brain.py já remove, em write_export, copy_to_files e move_out_of_inbox, só o que a própria chamada criou (pasta de staging, cópia incompleta, reserva vazia). O teste falharia sem relação com o backup. | grep de os.remove/unlink/rmdir/rmtree no brain.py 2026.11.2 | Architect + thomas | Emenda v1 (contrato inalterado) — lista fechada de limpezas no UT-07 e no ADR-0015 | 2026-11-02 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0051`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 1 (emenda v1, contrato inalterado) | 2026-11-02 | UT-07 e o Mapa aceitam, além de `rotate_backups`, a lista fechada de limpezas existentes (`write_export`, `copy_to_files`, `move_out_of_inbox`), que só removem o que a própria chamada criou; ADR-0015 ajustado | IMP-01: o `brain.py` 2026.11.2 já tem essas três limpezas, e o teste reprovaria código correto | Nenhuma | thomas, 2026-11-02 ("pode fazer no piloto automático com o recomendado") |
