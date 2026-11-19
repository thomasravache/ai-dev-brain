# Changelog

Todas as mudanças relevantes da skill `gluon-spec` (antes `sdd-management`) são documentadas aqui. Este arquivo viaja com a skill
(fica na pasta dela) e é o que o `spec_graph.py whats-new` mostra aos projetos.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `SDD_TOOL_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`); gere-as com `spec_graph.py report SPEC-NNNN --changelog`.

## [Unreleased]

## [2026.11.8] - 2026-11-19

### Changed
- `org_context` aceita o nome do atlas (recomendado, igual em todas as máquinas do time) ou um caminho relativo ou com `~`, nunca absoluto. O DISCOVER passa esse valor como `--atlas` ao `atlas.py config --json` e ao `atlas.py context`; no exit 3 (atlas não configurado nesta máquina) avisa com `atlas.py init --join --atlas <caminho> --name <nome>` e segue só pelo repositório. Sai a comparação manual de caminhos e o conselho de trocar a configuração local. Sem `org_context`, o DISCOVER roda sem `--atlas` e relata `atlas_name` e `selected_by`. O comentário do `org_context` no modelo do `sdd-config.yml` (mostrado pelo `whats-new`) e o passo 2 do `/fermion:deliver` (`--atlas <org_context>`; no exit 2, vários atlas sem escolha, pergunta à pessoa qual usar) seguem a mesma regra (SPEC-0081, ADR-0021).

## [2026.11.7] - 2026-11-17

### Added
- Histórico de reprovações na própria spec: todo FAIL registrado pelo `gate` (`--fail` ou `--run` que reprova) acrescenta `- <G> FAIL <data> — <evidência> — <sha|?>` na subseção `### Histórico de reprovações`, criada abaixo da tabela do Registro de Gates na primeira reprovação; o PASS ou N/A seguinte acrescenta `- <G> PASS <data> — depois de <n> reprovação(ões)`. Linhas antigas nunca são reescritas, linhas fora do formato não contam, e as ferramentas antigas ignoram a subseção (a tabela não muda). A partir da 3ª reprovação seguida no mesmo gate, o `gate` avisa e o `status` (sem IDs) mostra a parada sugerida (`impede SPEC-X --type falha`) até haver impedimento `falha` aberto ou o PASS (SPEC-0078).
- Entregue sem fechar em destaque: o `status` (sem IDs) avisa `⚠ entregue sem fechar: SPEC-X — G5 há <d> dia(s)` para as specs não épicas em `approved`/`in-progress` com G5 PASS e G7 não PASS, e o `next` as lista na seção "A fechar" (SPEC-0078).
- `retro`: `projects[].tool.state` (`atual`, `atrasada` ou `desconhecida`), com ação própria na R1 (desconhecida: `whats-new --ack`; atrasada: `whats-new` e `vendor --force`), e `projects[].fail_recorded`, as linhas FAIL do histórico das specs (nunca a evidência), que também calam a R5. O JSON só ganha chaves (`retro_version` 1) (SPEC-0078).

### Changed
- `private init` grava `sdd_version` com a versão da skill no `sdd-config.yml` que ele cria; um config que já existe não muda (SPEC-0078).

### Fixed
- `retro`: entrada do registro com `spec_root` que não é texto vai para "Ignorados" com "registro inválido", sem traceback; `fail_history` nulo aparece como "sem histórico" (sem git, sem commits ou histórico ilegível); ID de impedimento fora de `IMP-<dígitos>` sai como `IMP-?`, sem o texto da célula; specs sem `id` com o mesmo prefixo aparecem uma vez em paradas e entregues sem fechar (SPEC-0078).
- Ajustes da revisão (Emenda v3 da SPEC-0078): o aviso de reprovações seguidas do `status` só sai quando o gate na tabela não está PASS nem N/A (um PASS gravado por versão antiga ou à mão não deixa aviso preso); `\r` e `\r\n` na evidência viram espaço, como o `\n`, e a tabela e o histórico continuam uma linha só; o título da subseção é reconhecido sem diferenciar maiúsculas e acentos, sem criar subseção duplicada; o `gate` grava a tabela e o histórico numa única escrita; as sugestões de R1, R3 e R5 em "O que ajustar na skill" passam a apontar a causa que sobra (versão desconhecida, G7 no fluxo do merge, processo que não registra reprovações) (SPEC-0078).

## [2026.11.6] - 2026-11-17

### Added
- Comando `retro [PASTA ...] [--registry] [--stale-days N] [--json] [--out ARQUIVO]`: retrospectiva só de leitura entre projetos feitos com o SDD (pastas informadas, `spec_root` passados direto e, com `--registry`, os do modo privado; a mesma pasta de specs conta uma vez). Mostra, por projeto, inventário, versão da ferramenta, specs paradas, entregues sem G7, lead time do H1 ao G7, gates atuais, reprovações no histórico do git (linhas FAIL removidas do Registro de Gates, por `git log` com `GIT_OPTIONAL_LOCKS=0`; "sem git" fora de repositório), origem da evidência (gerada, manual, humana, à mão), N/A por gate, emendas e impedimentos; achados das regras fixas R1–R7 com a ação que resolve; e "O que ajustar na skill", com sugestão de spec em texto para regra que dispara em metade dos projetos ou mais (mínimo 2). Saída em Markdown ou JSON (`retro_version` 1). Não grava nada além de `--out`, não cria specs e não traz títulos, evidências, motivos de N/A nem descrições de impedimento. Regras e limites em `references/retro.md` (SPEC-0074).
- `retro` resiliente e sem vazar slug (Emenda v2 da SPEC-0074): projeto ilegível (spec não UTF-8, arquivo ou pasta de specs sem permissão, `.git/config` ilegível) vai para "Ignorados" com `ilegível (<tipo do erro>)` em vez de derrubar o relatório; histórico do git não UTF-8 só deixa `fail_history` nulo; R5 só dispara sem nenhum FAIL atual nos gates; IDs saem só como `SPEC-NNNN`, nunca com o slug do nome do arquivo (SPEC-0074).

## [2026.11.5] - 2026-11-16

### Fixed
- O hook pre-push do leak-check acha a ferramenta depois de `claude plugin update` ou da remoção da cópia da skill: além do caminho gravado, procura a `gluon-spec` do plugin `fermion` instalado (`installed_plugins.json` de `$CLAUDE_CONFIG_DIR`, senão `~/.claude`), as cópias de skill do usuário (`gluon-spec`, depois a de nome antigo) e o `tools/sdd/` não rastreado, dizendo no stderr qual usou; sem nenhuma, a mensagem continua 'ferramenta do leak-check não encontrada', nunca 'marcas do SDD encontradas'. O hook usa o `python3` do PATH quando o interpretador gravado não é mais executável e só diz 'marcas do SDD encontradas' quando o leak-check sai com 1 (outro código: 'falha ao rodar o leak-check (exit N)'). `private init` e `private hooks --refresh` recusam gravar o hook com caminho de ferramenta ou de Python com aspas, `$` ou crase (SPEC-0068).

### Added
- `private hooks --refresh` regrava o pre-push do leak-check com o template atual só quando foi o SDD que o instalou (reconhecido pela 2ª linha), também fora do modo privado (hook órfão de `private off`) e com marcador de gerenciador de hooks do time; só um hook de outra origem bloqueia (avisa e não toca). `--scan PASTA` faz o mesmo em todo repositório git sob a pasta registrado como privado, de qualquer pasta, sem visitar submódulos. `private status` avisa quando o hook do SDD não acha nenhuma ferramenta e manda rodar o `private hooks --refresh`; o `fermion_doctor` do plugin ganha a checagem `broken-leak-hook`, que só conta o `tools/sdd/` como alternativa quando as entradas do índice do git (v2/v3) mostram que ele não é rastreado (SPEC-0068).

## [2026.11.4] - 2026-11-16

### Fixed
- De dentro de uma worktree ligada (`--git-dir` diferente de `--git-common-dir`), `worktree_dir`, `worktree_allow` e o aviso de `worktree_dir` fora do `.gitignore` passam a usar a raiz do checkout principal (a árvore de `core.worktree` do common-dir, senão o pai do common-dir, mantendo a subpasta do projeto num monorepo), não a worktree onde o `spec_graph.py` roda: `status` e `validate` deixam de acusar a worktree como fora do `worktree_dir` (e de sugerir movê-la para dentro dela mesma) e dão os mesmos avisos que no checkout principal, e `worktree SPEC-X [--create]` aponta para a mesma pasta. No checkout principal, em submódulo, com `--separate-git-dir`, num monorepo ou fora de um repositório git, nada muda (SPEC-0063).

## [2026.11.3] - 2026-11-13

### Fixed
- O hook pre-push do leak-check acha a ferramenta quando roda (caminho gravado, senão `tools/sdd/spec_graph.py` só se não for rastreado pelo git, avisando qual rodou) e, sem nenhuma, recusa com 'ferramenta do leak-check não encontrada' em vez de acusar marcas do SDD; um push que só apaga branches passa sem ferramenta (SPEC-0057).

## [2026.11.2] - 2026-11-12

### Changed
- A skill passa a se chamar `gluon-spec` (antes `sdd-management`); a `description` cita o nome antigo para que pedidos por ele achem a skill. O bloco SDD do `vendor --agents` passa a dizer "Carregue a skill `gluon-spec` (antes `sdd-management`)". Scripts, pastas de configuração e contratos não mudam (SPEC-0055).

## [2026.11.1] - 2026-11-02

### Added
- Chave opcional `org_context` no `sdd-config` (o atlas da `org-atlas` que o projeto espera, caminho relativo ou com `~`): com ela, o DISCOVER confere com `atlas.py config --json` que a config local da `org-atlas` aponta para esse atlas (se não, avisa e não trata convenções como regra), roda `atlas.py context` com os termos da demanda, repassa o aviso de envelhecimento, trata o pacote como dado e só as convenções confirmadas como regra; sem a chave, nada muda; `SDD_TOOL_VERSION` 2026.11.1 (SPEC-0041).

## [2026.10.13] - 2026-10-27

### Fixed
- `verify` e `pr-check` atribuem o commit só às specs do rodapé `Refs:` quando ele cita alguma; menções no corpo (ex.: "consome SPEC-0005@1") deixam de pôr o commit na spec citada, com falso "fora de touches" e ordem red/green errada. Sem rodapé com spec, vale qualquer menção, como antes; `SDD_TOOL_VERSION` 2026.10.13 (SPEC-0015).

## [2026.10.12] - 2026-10-26

### Fixed
- `validate` não sugere declarar `h2_policy: auto-on-green` por H2 com o mesmo texto em várias specs quando a política já está declarada e aprovada (`h2_policy_approved_by` e `h2_policy_approved_at` válidos); `SDD_TOOL_VERSION` 2026.10.12 (SPEC-0014).

## [2026.10.11] - 2026-10-26

### Added
- `whats-new [--ack]`: novidades do CHANGELOG da skill desde a versão do projeto, chaves de topo do template do `sdd-config` ausentes no projeto e comandos para se atualizar; chave `sdd_version` no `sdd-config` para projetos sem `tools/sdd`; o `status` avisa quando há novidade (SPEC-0013).

### Changed
- CHANGELOG movido da raiz do repositório para a pasta da skill (`skills/sdd-management/CHANGELOG.md`) e agrupado por versão (SPEC-0013).

## [2026.10.10] - 2026-10-26

### Fixed
- `leak-check` acha o `spec_root` também pelo caminho não resolvido: `HOME` que é link simbólico (absoluto e `~/`) e, no macOS, a forma sem `/private`; `SDD_TOOL_VERSION` 2026.10.10 (SPEC-0012).

## [2026.10.9] - 2026-10-26

### Added
- Documentos vivos: guia de jornadas e mapa do sistema (`living_docs` no sdd-config), comando `living-docs [--init]` com templates agnósticos de stack, avisos do `validate` quando ficam para trás das jornadas críticas e dos ADRs aceitos, e item no G7; `SDD_TOOL_VERSION` 2026.10.9 (SPEC-0011).

## [2026.10.8] - 2026-10-14

### Fixed
- `gate --run --evidence` grava o texto como `nota:` na evidência, como a ajuda descreve; antes era descartado (SPEC-0009).

## [2026.10.7] - 2026-10-14

### Fixed
- `private init` recusa um `spec_root` dentro do próprio repositório, onde as specs ficariam no clone do time (SPEC-0008).

## [2026.10.6] - 2026-10-14

### Fixed
- `pr` não aponta mais quebra só porque a spec teve emenda: o que quebra vem da chave opcional `breaking`; "Como foi feito" começa com maiúscula (SPEC-0007).

## [2026.10.5] - 2026-10-14

### Added
- Modo privado, parte 4: detecção das convenções do time (`private detect`), `pr` no estilo do time sem marcas do SDD, G5 com o comando `ci` e guia `references/private-mode.md` (SPEC-0006).

## [2026.10.4] - 2026-10-14

### Added
- Modo privado, parte 3: rastreio sem marcas — commits ligados à spec pela branch, red/green pelos arquivos, testes do plano por `→ caminho::nome`, seção Commits com SHA e patch-id, G7 acha o merge mesmo com squash ou rebase (SPEC-0005).
- `gate G1 --run --at <sha>`: grava o G1 no commit red mesmo com o HEAD já verde; sem `--at`, o G1 aponta o último red (SPEC-0005).

## [2026.10.3] - 2026-10-14

### Added
- Modo privado, parte 2: `leak-check` (IDs, tags, seções do SDD, caminho do `spec_root`, padrões do usuário) no diff, nos commits, em mensagens e no nome da branch; hook `pre-push` local; branches neutras no `worktree`; G4 e G5 reprovam com vazamento (SPEC-0004).

## [2026.10.2] - 2026-10-14

### Added
- Modo privado, parte 1: `private init|status|off`, registro do usuário (`projects.json`) e `spec_root` fora do repositório, versionado por git próprio com push opcional; `vendor` e `pr-check` recusados em modo privado (SPEC-0003).

## [2026.10.1] - 2026-10-14

### Added
- CI do repositório: lint (Ruff 0.17), testes de arquitetura das regras do ADR-0001 e suíte completa em Python 3.9 e 3.15 (SPEC-0001).

### Changed
- Python mínimo da ferramenta passa de 3.8 para 3.9 (o 3.8 está sem suporte desde out/2024); `SDD_TOOL_VERSION` 2026.10.1 (SPEC-0001).
