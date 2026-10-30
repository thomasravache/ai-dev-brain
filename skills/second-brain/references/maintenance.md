# Manutenção do vault (`lint`)

`brain.py lint [--json] [--only regra1,regra2]` aponta o que está deixando o segundo cérebro pior. Ele **só lê**: não corrige, não move e não apaga nada (ADR-0007). As correções são propostas pelo agente e feitas só com o sim da pessoa, pelos comandos que criam e acrescentam (`relate`, `index`, `new-note`). O fluxo está na seção **Manter o vault (lint)** do `SKILL.md`.

Quando rodar: a pessoa pede; o `doctor` mostra a linha `lint` com achados; depois de processar a inbox.

## Saída

- **Texto:** uma linha por achado, `<ERRO|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)`, os erros primeiro, e no fim o resumo `N erros, M avisos`.
- **JSON (`--json`):** `{"findings": [{"rule", "severity", "path", "detail", "suggestion"}], "summary": {"error": N, "warn": M}}`. `path` é relativo ao vault, com `/` (o achado `config` da pasta `files` usa `<files>`).
- **Exit:** 0 sem erro (só avisos, ou nada); 1 com algum erro; 2 com regra desconhecida em `--only` (a mensagem lista as regras).
- **`doctor`:** uma linha `OK|AVISO|ERRO lint — N erros, M avisos (rode lint)`; ERRO quando há erro (e o `doctor` sai com 1), AVISO quando só há avisos, OK sem achados.

O `lint` lê o vault uma vez só (as mesmas pastas da busca: sem `.obsidian/`, `.trash/`, outras pastas ocultas e `templates/`) e roda as regras sobre essa leitura. Num vault de 5.000 notas leva menos de 3 s.

## Regras

| Regra | Severidade | O que aponta | Correção proposta |
|---|---|---|---|
| `broken-link` | erro | `[[link]]` que não resolve para nenhuma nota (a mesma resolução do Obsidian que o `links` usa) | criar a nota com `new-note` ou corrigir o link |
| `conflict-copy` | erro | arquivo cujo nome casa com `conflict_patterns` e cujo original (`<base>.md`) existe na **mesma** pasta | a pessoa compara a cópia com o original e escolhe; a skill não mescla nem apaga |
| `missing-file` | erro | caminho de `files:` no frontmatter que não existe na pasta `files`; um caminho absoluto ou que sobe com `..` aparece como "fora da pasta files" | conferir se o arquivo sincronizou nesta máquina, ou corrigir o caminho |
| `orphan` | aviso | nota sem link de saída que resolve, sem link de entrada e fora de qualquer MOC | `relate` com uma nota próxima ou uma nota nova que a ligue; o `index` só a põe no MOC quando ela tem contexto |
| `stale-inbox` | aviso | item da inbox mais velho que `inbox_stale_days` (padrão 7) | processar a inbox (seção da inbox no `SKILL.md`) |
| `frontmatter` | aviso | nota de um tipo da skill (`note`, `lecture`, `source`, `video`, `document`, `link`, `moc`, `answer`) sem `title` ou sem `created`, ou nota com frontmatter que não é lido (YAML inválido ou sem o `---` de fechamento) | mostrar o que falta; a pessoa (ou o agente, com o sim dela) completa o frontmatter |
| `config` | erro | regex inválido (ou sem o grupo `base`) em `conflict_patterns`; pasta `files` inacessível (sem permissão, inexistente ou sem `files` na configuração local) | corrigir o `brain-config.yml` ou a pasta `files` (`brain.py doctor`) |

Detalhes que valem para as regras:

- **Anexos (`broken-link`):** um link ou embed para um arquivo que não é nota (`![[foto.png]]`, `[[slides.pdf]]`) só é link quebrado quando **nenhum** arquivo com esse nome (ou esse caminho) existe no vault. Como no Obsidian, o anexo é procurado pelo nome do arquivo, sem diferença de maiúsculas e minúsculas, em qualquer pasta do vault. Anexo que existe nunca é achado.
- **Seções e apelidos (`broken-link`):** `[[Nota#seção]]` e `[[Nota|apelido]]` valem pela nota; a seção não é conferida.
- **Órfãs (`orphan`):** não são avaliadas as notas de `raw/`, `inbox/`, `mocs/` e `templates/`, nem o `index.md` e o `log.md`. Um link vindo de um MOC conta como entrada (a nota está no MOC). As listas do `index.md` e do `log.md` não contam como entrada: são geradas pelo `brain.py` e não ligam a nota a nada. Link de uma nota para ela mesma não conta.
- **Cópias de conflito (`conflict-copy`):** sem o original na mesma pasta não há achado (`Aula 2.md` sozinho é só uma nota). Os padrões de cada provedor estão em `references/providers.md`.
- **`frontmatter`:** capturas da inbox (`type: capture`) não entram nesta regra; elas aparecem em `stale-inbox` quando ficam paradas.
- **`config`:** regex com quantificador aninhado (`(a+)+`, `(a+){20}` e variações) ou com mais de 500 caracteres é recusado sem ser usado (travaria o `lint`). A verificação é de melhor esforço: alternativas sobrepostas, como `(a|aa)+`, não são detectadas; use padrões simples. Com regex inválido ou recusado, os outros padrões e as outras regras rodam normalmente. Com a pasta `files` inacessível, a regra `missing-file` é pulada (não daria para saber o que falta). Com `--only`, o achado `config` aparece quando `config` foi pedido ou quando ele afeta uma regra pedida (`conflict-copy` ou `missing-file`).

## Nunca apagar

O `lint` nunca apaga, e o agente também não: nem a cópia de conflito, nem a nota órfã, nem o item parado na inbox. Para um conflito, mostre os dois caminhos e oriente a pessoa a comparar no Obsidian; se ela quiser descartar a cópia, quem apaga é ela.
