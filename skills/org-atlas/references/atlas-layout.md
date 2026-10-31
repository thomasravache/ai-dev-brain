# Estrutura do atlas

O `atlas.py init` cria a estrutura numa pasta vazia ou inexistente. Os nomes de pastas e arquivos são sempre em inglês; o conteúdo segue o idioma da organização (`language` no `atlas-config.yml`).

```text
<atlas>/
  ATLAS.md            # página de entrada: o que é o atlas, serviços, última coleta
  atlas-config.yml    # configuração compartilhada (references/config.md)
  glossary.md         # termos, siglas e nomes internos
  services/           # uma página por serviço (SPEC-0036)
  platform/           # infraestrutura, entrega, dados
  conventions/        # padrões de código e de repositório
  process/            # como o time trabalha
  snapshots/          # saída dos coletores (SPEC-0033)
```

Cada pasta vazia ganha um `.gitkeep`, para a estrutura chegar a quem clona o atlas no modo `repo`. Uma pasta que só tem `.git/` (repositório recém-criado ou clonado vazio) conta como vazia para o `init`.

## Regiões geradas

`ATLAS.md` e `glossary.md` vêm de `assets/pages/` e têm regiões que o `atlas.py` mantém:

```markdown
<!-- atlas:begin services -->
_(nenhum serviço mapeado ainda)_
<!-- atlas:end services -->
```

- `ATLAS.md`: `about`, `services`, `snapshots`.
- `glossary.md`: `terms`.

O `atlas.py` só reescreve o que fica entre `<!-- atlas:begin <nome> -->` e `<!-- atlas:end <nome> -->` (e os snapshots e arquivos gerados). O texto fora das regiões é de quem mantém o atlas e nunca é alterado (ADR-0010).

## Só metadados

O atlas guarda nomes, estrutura e relações. Nunca guarda valor de segredo, dado de negócio nem código-fonte da organização; credenciais ficam na configuração local de cada máquina, só pelo nome.
