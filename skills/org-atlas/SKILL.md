---
name: org-atlas
description: >-
  Atlas de como uma organização desenvolve e opera software — serviços, plataforma, convenções, processo e glossário em Markdown, mantido junto com os agentes num repositório compartilhado ou numa pasta local, com a configuração em duas camadas (compartilhada no atlas, local por máquina com as credenciais só pelo nome). Use quando o usuário quiser mapear a organização para os agentes, configurar o atlas pela primeira vez (onboarding: organização, modo repo ou local, onde fica o atlas, credenciais por nome), ligar uma máquina nova a um atlas existente (init --join), ver a configuração (config), diagnosticar o que está configurado, o que funciona e o que falta (doctor) atualizar o atlas com os dados dos coletores declarados (scan: roda os coletores, valida o contrato, mascara segredos, grava os snapshots e mostra o que mudou) ou refazer o grafo e as páginas a partir dos snapshots (build: junta as fontes no graph.json, infere quem usa qual banco, fila ou serviço e gera ATLAS.md, services/<id>.md e platform/<categoria>.md sem tocar no texto do time).
---

# Org Atlas

Você ajuda a pessoa a manter um **atlas** de como a organização desenvolve e opera software: quais serviços existem, como são entregues, que plataforma usam, quais convenções e processos o time segue. O atlas é Markdown que pessoas e agentes leem; tudo o que é determinístico (estrutura, configuração, diagnóstico) é feito pelo `scripts/atlas.py`, nunca à mão.

A skill é **agnóstica de organização, de provedor e de agente**: o `atlas.py` só precisa de Python 3.9+, guarda só metadados (nomes, estrutura, relações) e nunca guarda nem imprime o valor de um segredo (ADR-0010).

## Ferramenta

Rode `python3 <skill-dir>/scripts/atlas.py <comando>`, onde `<skill-dir>` é a pasta deste `SKILL.md`.

| Comando | Uso |
|---|---|
| `config [--json]` | Configuração efetiva, com a origem de cada valor (`local`, `atlas` ou `padrão`); credenciais só pelo nome. Exit 3 = não configurado nesta máquina; exit 2 = `credentials` com algo que não é nome de variável |
| `init --atlas P --org NOME --mode repo\|local [--force]` | Cria um atlas novo numa pasta vazia ou inexistente: estrutura, `atlas-config.yml` e a configuração local. Mesmo `atlas-config.yml` = "Atlas já configurado" (só a configuração local). `atlas-config.yml` diferente sai com 2, a menos que `--force` (o anterior vai para `atlas-config.yml.bak`, ou `.bak.1`, `.bak.2`… sem apagar backup antigo). Pasta com conteúdo e sem `atlas-config.yml` sai com 2 |
| `init --join --atlas P` | Máquina nova para um atlas que já tem `atlas-config.yml`: grava só a configuração local; sem ele sai com 2. Não aceita `--org`, `--mode` nem `--force` (sai com 2): organização e modo vêm do atlas |
| `doctor [--json]` | Uma linha `OK\|AVISO\|ERRO <item> — <detalhe>` por item: configuração local, pasta do atlas, `atlas-config.yml`, estrutura, git, cada coletor e cada credencial (`definida` ou `não definida`, nunca o valor). Exit 0 sem ERRO, 1 com ERRO, 3 sem configuração |
| `scan [--only id,...] [--json]` | Roda cada coletor habilitado em `collectors` (ou só os de `--only`), valida a saída contra o contrato `org-atlas/collector@1`, mascara segredos (`[REDACTED]`), grava `snapshots/<id>.json` e `snapshots/_scan.json` e imprime por coletor `OK <id> — +A entidades, -R, ~C; +a relações, -r`, `OK <id> — sem mudanças`, `N valor(es) mascarado(s)` ou `FALHA <id> — <motivo>`, e no fim roda o `build`. Exit 0 sem falha, 1 com alguma falha (os outros coletores seguem), 2 com configuração inválida ou `--only` com id não declarado. Sem coletor habilitado nada roda nem é gravado. `--json` imprime um objeto só, com o relatório do `build` na chave `build` |
| `build [--json]` | Junta os snapshots de `snapshots/` no `graph.json` (um nó por `kind:id`, conflito de atributo registrado e resolvido pela ordem de `collectors`), infere `sourced_from` (serviço → repositório) e `depends_on` (serviço → banco, fila, tópico, bucket ou outro serviço, pelo host de `config_refs`) e atualiza só as regiões geradas de `ATLAS.md`, `services/<id>.md` e `platform/<categoria>.md`. Imprime `Grafo: N nós, M arestas (I inferidas), C conflitos; P páginas atualizadas`; snapshot ilegível = `aviso: ...` e o build segue. Roda sozinho no fim de todo `scan` |

Detalhes das duas camadas de configuração: `references/config.md`. Estrutura do atlas e regiões geradas: `references/atlas-layout.md`. Contrato dos coletores e o `scan`: `references/collector-contract.md`. Padrões de mascaramento: `references/redaction.md`. Formato do `graph.json`, regras de junção e de inferência e as páginas geradas: `references/graph.md`. Coletores da skill: `references/collectors/generic.md` (fatos escritos à mão), `references/collectors/github.md` (repositórios, pipelines, times e sinais) e `references/collectors/argocd.md` (deployments, serviços, ambientes e clusters).

## Antes de qualquer fluxo

Rode sempre `atlas.py config` antes de qualquer fluxo, em toda conversa — não confie na memória:

- **Configurado (exit 0)** → siga direto o fluxo pedido, sem perguntar nada de configuração.
- **Exit 3** ("org-atlas não configurado nesta máquina") → faça o **onboarding** abaixo, ou o `init --join` se o atlas já existir.
- **Exit 2** (credencial com valor) → mostre a mensagem e peça para trocar o valor pelo **nome** da variável na configuração local; nunca copie o valor para lugar nenhum.
- **Exit 1** ou valores estranhos → rode `atlas.py doctor` e mostre o resultado antes de seguir.

## Onboarding (exit 3)

Converse com a pessoa; o `atlas.py init` não é interativo e recebe tudo por flags.

1. **Atlas novo ou existente:** pergunte se a organização já tem um atlas.
   - Já tem (um repositório ou pasta com `atlas-config.yml`) → vá para **Máquina nova** abaixo.
   - Não tem → siga os passos 2 a 5.
2. **Organização:** pergunte o nome da organização (vai para `organization` no `atlas-config.yml`).
3. **Modo:** pergunte onde o atlas vai viver.
   - `repo` — um repositório git compartilhado com o time. Peça para a pessoa criar (ou clonar) o repositório vazio e use essa pasta.
   - `local` — uma pasta só desta máquina.
4. **Onde fica o atlas:** pergunte o caminho da pasta (vazia ou inexistente; uma pasta só com `.git/` conta como vazia). Sugira um nome em kebab-case, como `~/<organização>-atlas`. Rode:

   ```bash
   python3 <skill-dir>/scripts/atlas.py init --atlas <pasta> --org "<organização>" --mode repo|local
   ```

   - No modo `local`, rode você mesmo `git init` na pasta do atlas depois do `init`, para ter histórico das mudanças: o `atlas.py` não executa nada além dos coletores (ADR-0010), e o `doctor` mostra AVISO enquanto a pasta não for um repositório git.
   - No modo `repo`, lembre a pessoa de fazer commit e push da estrutura criada.
5. **Credenciais por nome:** pergunte quais variáveis de ambiente ou profiles cada coletor vai usar (por exemplo `GITHUB_TOKEN`, profile `work`) e escreva **só os nomes** em `credentials` na configuração local (`references/config.md`). Nunca pergunte, copie, grave nem mostre o valor de um segredo; se a pessoa colar um valor, peça para trocar pelo nome da variável.
6. Rode `atlas.py doctor` e mostre o resultado.

### Máquina nova

O atlas já existe (clonado ou sincronizado nesta máquina):

```bash
python3 <skill-dir>/scripts/atlas.py init --join --atlas <pasta do atlas>
```

Depois declare as credenciais desta máquina pelo nome (passo 5) e rode `doctor`.

## Scan (atualizar o atlas com os coletores)

1. Rode `atlas.py config` (Antes de qualquer fluxo). Sem coletores em `collectors`, ajude a pessoa a declarar cada um no `atlas-config.yml` (`id`, `category`, `command` como lista, `timeout`, `enabled`) usando `{skill}` e `{atlas}` no lugar de caminhos absolutos (`references/collector-contract.md`), e rode `atlas.py doctor` para conferir os executáveis.
2. Rode:

   ```bash
   python3 <skill-dir>/scripts/atlas.py scan            # todos os coletores habilitados
   python3 <skill-dir>/scripts/atlas.py scan --only github,argocd
   ```

3. Mostre o resultado por coletor:
   - `OK <id> — ...` → o snapshot foi gravado; resuma o que entrou, saiu e mudou. Com `N valor(es) mascarado(s)` ou chave descartada, avise que o coletor está emitindo algo com cara de segredo e sugira corrigir o coletor (nunca tente recuperar o valor).
   - `FALHA <id> — <motivo>` → o snapshot anterior e o `seen_at` desse coletor ficam como estavam; os outros seguem. Mostre o motivo e as linhas de violação ou do stderr, e ajude a corrigir (credencial não definida, timeout curto, coletor fora do contrato).
   - Exit 2 → configuração inválida (por exemplo caminho absoluto em `command`) ou `--only` com id não declarado: nada rodou; mostre a mensagem e corrija o `atlas-config.yml`.
4. Mostre a linha `Grafo: ...` do `build` que o `scan` rodou no fim: quantas entidades e relações, quantas inferidas, quantos conflitos e quantas páginas mudaram. Com conflitos, aponte o atributo e os coletores (região `summary` da página ou `conflicts` no `graph.json`) e sugira corrigir a fonte errada ou a ordem de `collectors` (vale o primeiro).
5. No modo `repo`, os snapshots, o `graph.json` e as páginas são arquivos do atlas: lembre a pessoa de fazer commit (o diff do PR é o que o scan mostrou).

## Build (grafo e páginas)

Use `atlas.py build` para refazer o grafo e as páginas sem rodar os coletores (por exemplo depois de mudar a ordem de `collectors`, ou de apagar uma página por engano):

```bash
python3 <skill-dir>/scripts/atlas.py build
```

- O `graph.json` é refeito dos snapshots; com os mesmos snapshots ele fica idêntico. Leia-o (formato em `references/graph.md`) para responder perguntas como "quem usa o banco X" ou "de que repositório vem o serviço Y".
- Nas páginas, só as regiões `<!-- atlas:begin <nome> -->` … `<!-- atlas:end <nome> -->` mudam. Ajude o time a escrever contexto em `## Notas` ou em qualquer lugar fora das regiões: isso nunca é reescrito.
- Um serviço que sumiu dos snapshots mantém a página, com "_Não visto desde AAAA-MM-DD._"; pergunte à pessoa se o serviço foi desligado antes de sugerir apagar a página (apagar é decisão do time, nunca do `atlas.py`).
- `aviso: snapshots/<id>.json ilegível ...` → rode `scan --only <id>` para regravar o snapshot desse coletor.

## Regras

- **Nunca** grave nem mostre o valor de uma credencial: a configuração local guarda só nomes de variável (`^[A-Z_][A-Z0-9_]*$`) e de profile, e o `doctor` só diz `definida` ou `não definida`.
- O `atlas-config.yml` vai junto com o atlas: nunca coloque nele um caminho absoluto nem um segredo.
- Não edite `snapshots/` nem `graph.json` à mão: são do `atlas.py scan` e do `atlas.py build`. Nunca copie para o atlas, para a conversa ou para outro lugar um valor que o scan mascarou.
- Não edite à mão as regiões `<!-- atlas:begin <nome> -->` … `<!-- atlas:end <nome> -->`: são do `atlas.py`. O texto fora delas é de quem mantém o atlas.
- Não sobrescreva um `atlas-config.yml` diferente sem a pessoa pedir; o `--force` guarda o anterior em `atlas-config.yml.bak` (ou `.bak.1`, `.bak.2`…, nunca sobrescrevendo um backup).
