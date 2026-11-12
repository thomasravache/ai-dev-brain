# Estrutura do atlas

O `atlas.py init` cria a estrutura numa pasta vazia ou inexistente. Os nomes de pastas e arquivos são sempre em inglês; o conteúdo segue o idioma da organização (`language` no `atlas-config.yml`).

```text
<atlas>/
  ATLAS.md            # página de entrada: o que é o atlas, resumo, serviços, última coleta
  atlas-config.yml    # configuração compartilhada (references/config.md)
  glossary.md         # termos, siglas e nomes internos
  graph.json          # grafo de entidades e relações, gerado pelo build (references/graph.md)
  services/           # uma página por serviço, gerada pelo build (SPEC-0036)
  platform/           # uma página por categoria (code, ci, delivery, runtime, data...), gerada pelo build
  conventions/        # padrões de código e de repositório
  process/            # como o time trabalha
  snapshots/          # saída dos coletores (SPEC-0033)
```

Cada pasta vazia ganha um `.gitkeep`, para a estrutura chegar a quem clona o atlas no modo `repo`. Uma pasta que só tem `.git/` (repositório recém-criado ou clonado vazio) conta como vazia para o `init`.

## Regiões geradas

`ATLAS.md` e `glossary.md` vêm de `assets/pages/` no `init`; as páginas de serviço e de plataforma vêm de `assets/pages/service.md` e `assets/pages/platform.md` quando o `build` as cria. Todas têm regiões que o `atlas.py` mantém:

```markdown
<!-- atlas:begin services -->
_(nenhum serviço mapeado ainda)_
<!-- atlas:end services -->
```

- `ATLAS.md`: `about` (texto fixo do `init`), `summary` (contagens por tipo), `services` (lista com links) e `scans` (`seen_at` por coletor).
- `services/<id>.md`: `summary`, `repository`, `deployments` (por ambiente), `depends-on`, `used-by`, `owners`, `pipelines` e `sources`, seguidas de `## Notas` para o time.
- `platform/<categoria>.md`: `entities`, seguida de `## Notas`.
- `glossary.md`: `terms`.

O `atlas.py build` (que roda no fim de todo `scan`) reescreve as regiões a partir do `graph.json` e nunca apaga uma página: a de um serviço que sumiu dos snapshots fica, com `summary` = `_Não visto desde AAAA-MM-DD._` e as outras regiões vazias. Uma região que falta numa página existente não é recriada (seria texto fora das regiões); num `ATLAS.md` criado antes da 2026.11.1, a região `snapshots` recebe o conteúdo de `scans`; regras completas em `references/graph.md`.

O `atlas.py` só reescreve o que fica entre `<!-- atlas:begin <nome> -->` e `<!-- atlas:end <nome> -->` (e os arquivos gerados: `snapshots/` e `graph.json`). O texto fora das regiões é de quem mantém o atlas e nunca é alterado (ADR-0010).

## Só metadados

O atlas guarda nomes, estrutura e relações. Nunca guarda valor de segredo, dado de negócio nem código-fonte da organização; credenciais ficam na configuração local de cada máquina, só pelo nome.
