---
id: SPEC-0088
title: "boson-atlas: núcleo do probe — contrato de adaptador, verbos permitidos, ambientes e registro local"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-22
parent: SPEC-0030
depends_on: []
consumes_contract: [SPEC-0087@3]
contract_version: 6
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/probes.md, skills/boson-atlas/references/config.md, skills/boson-atlas/references/redaction.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0011, ADR-0023]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-23
---

# SPEC-0088 — boson-atlas: núcleo do probe — contrato de adaptador, verbos permitidos, ambientes e registro local

> Origem: épico SPEC-0030, primeira filha. Thomas decidiu em 2026-11-22 que a verificação da SPEC-0075 usa as probes.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Comando `atlas.py probe`, desligado por padrão, que roda uma consulta **só de leitura** na infraestrutura real por meio de um adaptador externo declarado (contrato `probe@1`).

O atlas monta o alvo a partir do grafo e do mapa de acesso (SPEC-0087). Antes de executar, o núcleo verifica três coisas:
- o verbo está na lista permitida;
- o ambiente é de teste, ou houve confirmação de produção;
- a máquina tem acesso ao cluster.

Depois de executar, o núcleo valida e limita a saída, mascara segredos e registra a consulta localmente, sem o resultado.

## 2. Motivação & Escopo
**Motivação:** a verificação depois do deploy (SPEC-0090) e a investigação (SPEC-0030) precisam consultar o cluster e os logs com as mesmas proteções. Sem um núcleo, cada uso montaria comandos à mão, sem lista de verbos e sem redaction garantida.

**Objetivos (dentro do escopo):**
- `atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>`, com as opções `--since`, `--lines`, `--summary`, `--confirm-production` e `--json`.
- Chave local `probes` no `config.yml`, com `enabled`, adaptadores (comando, verbos, timeout, credenciais por nome) e limites.
- Contrato `probe@1`:
  - a descrição do adaptador (`--describe`);
  - a entrada em JSON pelo stdin;
  - a saída em JSON, que o núcleo valida.
- Recusas com exit 4: probes desligadas, verbo fora da lista, produção sem confirmação, cluster sem acesso local.
- Redaction com as regras do atlas, limite de linhas e resumo de logs por assinatura (`--summary`).
- Registro local em JSON Lines na pasta da configuração da máquina, sem o resultado.
- `doctor` com as linhas das probes: ligadas ou desligadas, e cada adaptador encontrado ou não.

**Não-objetivos (fora do escopo):**
- Adaptadores concretos: runtime é a SPEC-0089; SQL, nuvem e observabilidade ficam para ondas seguintes.
- Verbos de escrita, em qualquer forma.
- Tool MCP de probe e política no servidor (SPEC-0031).
- Gravar qualquer resultado no atlas.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0087@3. São usados o `tier` do ambiente, o `namespace` e os `workloads` do deployment, e `access.clusters` da configuração local.
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **processo externo declarado com contrato JSON:** os coletores (`run_collector`, `collector_environment` e a validação do `collector@1` em `scripts/atlas.py`, `references/collector-contract.md`);
- **redaction:** `references/redaction.md`;
- **chave local só com nomes:** `credentials` (ADR-0010);
- **testes:** os coletores falsos de `tests/fixtures/fake-collectors/`.

**Decisão:** `probe` é um subcomando do `atlas.py` que roda adaptadores como processos externos, igual aos coletores. Ele tem contrato próprio e versionado (`probe@1`) e segue o ADR-0023.

**Justificativa:**
- Reaproveita o modelo dos coletores, que já tem execução isolada, credenciais por nome, timeout e validação.
- Deixa as proteções num lugar só, testável.

**Desvio do padrão existente:** nenhum. É um contrato novo no mesmo molde do `collector@1`.

**Alternativas descartadas:** o agente rodar as CLIs direto, e um servidor MCP já agora (ADR-0023).

**ADRs:** ADR-0023 (criado pelo épico SPEC-0030 e por esta spec), ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** timeout por adaptador (padrão 60 s, máximo 300 s). A saída é limitada a `--lines` (padrão 200, máximo 2.000) e a 1 MB lido do adaptador.
- **Segurança:**
  - lista de verbos e confirmação de produção (ADR-0023);
  - o adaptador recebe só as credenciais declaradas nele, por nome;
  - redaction em todo texto da saída;
  - a mensagem de erro do adaptador também passa pela redaction;
  - nada é gravado no atlas.
- **Privacidade e dados pessoais:** os padrões de redaction do atlas valem para as linhas de log (e-mail, token, documento). O registro local não guarda resultado.
- **Disponibilidade e resiliência:**
  - adaptador ausente, saída inválida ou timeout → exit 1 com o motivo, sem saída parcial;
  - sem a chave `probes` → exit 4 "probes desligadas".
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** subcomando `probe`, chave local `probes`, contrato `probe@1` e registro local.

```text
config.yml (local; na forma com vários atlas, dentro da entrada do atlas)
  probes:
    enabled: false                     # padrão; true liga
    limits: {lines: 200, since: 30m}   # padrões; máximo lines 2000, since 24h
    adapters:
      kubernetes:                      # id do adaptador; sem command = o adaptador que vem com a skill
        command: ["python3", "/caminho/adaptador.py"]   # opcional
        verbs: [status, events, logs]  # liberados por esta máquina (interseção com os do adaptador)
        timeout: 60
        credentials: [NOME_DA_ENV]     # só nomes (ADR-0010)
  inválido → exit 2: "probes: <campo> inválido — <motivo>" (sem o valor)

atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>
    [--since 30m] [--lines N] [--summary] [--confirm-production] [--json] [--atlas X]
  1. sem probes.enabled: true → exit 4 "probes desligadas nesta máquina (probes.enabled)"
  2. alvo: deployments de service:<id> que runs_in environment:<ambiente>; nenhum → exit 2
  3. adaptador: o primeiro em adapters que declara <capacidade>; nenhum → exit 4 "nenhum adaptador para <capacidade>"
  4. verbo fora de (verbos do --describe ∩ verbs da configuração) → exit 4 "verbo <v> não permitido"
  5. tier do ambiente diferente de "test" (inclui sem tier) e sem --confirm-production → exit 4
     "ambiente <a> é de produção ou sem marcação: confirme com a pessoa e use --confirm-production"
  6. cluster do deployment sem access.clusters → exit 4 "sem acesso local ao cluster <c> (access.clusters)"
  7. roda o adaptador com a entrada abaixo no stdin, as credenciais declaradas e o timeout
  8. valida a saída, aplica redaction e limites e imprime (Markdown ou --json); registra
  exit: 0 ok · 1 erro do adaptador ou saída inválida · 2 argumento ou configuração inválida
        · 3 sem configuração · 4 recusado

probe@1 — descrição: <command> --describe  →
  {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}
probe@1 — entrada (stdin):
  {"contract": "probe@1", "capability": "runtime", "verb": "logs",
   "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
              "context": "<access.clusters.<c>.context>", "namespace": "api", "workloads": ["Deployment/api"]},
   "limits": {"lines": 200, "since_seconds": 1800}}
probe@1 — saída (stdout):
  {"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "logs",
   "status": "ok" | "error", "items": [{<chave>: escalar | lista de escalares}], "truncated": false,
   "message": "texto curto"}
  chaves fechadas; items com no máximo `lines` itens (excedente → truncated: true); texto passa pela redaction

--summary (só para verbos que devolvem linhas de log: itens com "line")
  assinatura = linha com números, hexadecimais de 8 ou mais, UUIDs, e-mails e textos entre aspas trocados
  por marcadores; nível = error | warn | info | other pela palavra na linha
  itens: {"signature", "level", "count", "first_ts", "last_ts", "sample"} por (nível, assinatura), ordenados
  por nível e contagem

registro local: <pasta da configuração>/probes.log, uma linha JSON por probe:
  {"at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
   "confirmed_production": bool}   — nunca items, message nem o contexto
```

**Esclarecimentos (Emenda v2):**
- **CH-01 em duas partes:**
  - uma guarda que passa antes da mudança: sem a chave `probes` ou com `enabled: false`, `scan`, `build`, `context`, `doctor`, `lint` e `config --json` ficam iguais ao golden, tirando só as linhas novas do `doctor` sobre probes e a chave `probes` do `config --json`;
  - um teste de recusa (exit 4, "probes desligadas", nenhum processo roda, nem `--describe`).
- **Funções do validador (CT-01):** `validate_probe_describe`, `validate_probe_input` e `validate_probe_output`. Cada uma recebe o dado e devolve `list[str]`; vazia quer dizer válido.
- **Exemplos em `references/probes.md`:** em blocos cercados com a info `json probe@1 <describe|input|output> <valid|invalid>`. Há pelo menos um válido e um inválido de cada tipo.
- **`--summary`:**
  - cada item de log tem `ts` e `line`;
  - a ordem é error, warn, info e outros, e dentro de cada um por contagem decrescente.
- **Credenciais:** o adaptador recebe só as credenciais declaradas na entrada dele. Nenhum nome declarado para outro adaptador ou para os coletores chega a ele.
- **Comando do adaptador:**
  - o núcleo acrescenta `--describe` no fim do comando;
  - `command` aceita caminho absoluto.
- **Registro:**
  - uma probe recusada (verbo, produção, sem acesso) entra no `probes.log` com `exit: 4`;
  - com as probes desligadas nada roda e nada é registrado.
- **Deployment inexistente:** é exit 2 do próprio `probe`, com o nome na mensagem.
- **Mensagens:** os testes conferem estes pedaços de texto, que fazem parte do contrato:
  - "probes desligadas";
  - "verbo X não permitido";
  - "nenhum adaptador para X";
  - "sem acesso local ao cluster X";
  - "ambiente X é de produção ou sem marcação", junto de `--confirm-production`;
  - "lines" ou "since" no erro de argumento;
  - "tempo" ou "timeout" no estouro de tempo.

**Esclarecimentos (Emenda v3):**
- **`doctor`:**
  - sem a chave `probes`, não mostra linha de probe;
  - com a chave, mostra "ligadas, N adaptador(es)" ou "desligadas";
  - um executável de adaptador que falta é ERRO com as probes ligadas e AVISO com elas desligadas.
- **Redação:** só na saída das probes, entram padrões a mais além das regras do atlas e de `redaction.extra_patterns`: e-mail, CPF, CNPJ, `Bearer <token>` e `<nome>=<valor>` quando o nome indica senha, segredo, token ou chave. Os snapshots do `scan` não mudam.
- **Ambiente do adaptador:**
  - recebe só uma base fixa (PATH, HOME, usuário, idioma, fuso, pastas temporárias e as variáveis de sistema do Windows) mais as credenciais declaradas na entrada dele, pelo nome;
  - qualquer outra variável, como KUBECONFIG ou um perfil de nuvem, precisa estar declarada (vale para a SPEC-0089).
- **Alvo:**
  - com vários deployments do serviço no ambiente, vale o primeiro pelo id;
  - com vários clusters, vale o primeiro, pelo nome, que tem acesso local;
  - sem nenhum cluster acessível, ou com o deployment sem cluster, a probe é recusada (exit 4).
- **Escolha do adaptador:**
  - o `--describe` roda em cada adaptador, na ordem, até um declarar a capacidade;
  - um adaptador ausente ou com `--describe` falho para a probe com exit 1;
  - sem `command`, vale `assets/probes/<id>.py` da skill quando existe (é o caso da SPEC-0089); sem ele, exit 2;
  - sem `verbs` na configuração, nenhum verbo é permitido.
- **Resultado:**
  - `status: error` do adaptador dá exit 1; com `--json`, sai o objeto do contrato com `items: []` e a mensagem mascarada, cortada em 500 caracteres;
  - uma resposta com capacidade ou verbo diferente do pedido está fora do contrato;
  - `--summary` sem nenhum item com `line` dá exit 2.
- **Registro:**
  - os status são ok, error, invalid e refused;
  - os exit 2 depois da checagem de ligado também entram no registro;
  - a configuração inválida não entra.

**Esclarecimentos (Emenda v4):**
- **Contexto mascarado (M1 do G4):** depois de escolher o contexto, o núcleo mascara o valor dele em tudo o que vem do adaptador antes de imprimir ou registrar: itens (chaves e valores), `message`, a cauda do stderr, a amostra e a assinatura do `--summary` e o texto de falha do contrato. Vale o mesmo para os valores das credenciais declaradas do adaptador.
- **JSON do adaptador:**
  - aninhamento profundo (`RecursionError`) e as constantes `NaN`/`Infinity` contam como JSON inválido (exit 1, sem traceback);
  - nenhum número fora do JSON padrão sai em `--json`.
- **`--summary`:**
  - sem itens, sai exit 0 com zero assinaturas, porque uma janela vazia é resposta válida;
  - itens sem nenhum `line` continuam dando exit 2.
- **`command` local:** o primeiro elemento é um nome sem separador de pasta (procurado no PATH) ou um caminho absoluto. Um caminho relativo é recusado na validação (exit 2) e no `doctor`.
- **Campos do alvo:** antes de rodar, o núcleo confere os campos que vêm do atlas e recusa com exit 2, sem rodar nada:
  - `namespace` segue o DNS-1123 (até 63 caracteres);
  - cada `workload` é `Kind/nome`, com o nome em DNS-1123 subdomínio;
  - `service`, `deployment` e `environment` seguem a regra de nome simples do atlas;
  - nenhum desses campos começa com `-`.
  Assim nenhum adaptador recebe um texto que pareça uma opção de linha de comando.
- **Campo `adapter` da saída:** precisa ser igual ao id do adaptador que rodou. Diferente, a saída está fora do contrato (exit 1).
- **Regras de nome:** a "regra de nome simples" é a do `ENVIRONMENT_NAME_RE` de `references/config.md`. No `Kind/nome`, o Kind só não pode começar com `-`.
- **Documentação:** a lista do ambiente do adaptador em `references/config.md` e `references/probes.md` fica igual à do código.

**Esclarecimentos (Emenda v5):**
- **Ordem da máscara:**
  1. os padrões de segredo (regras do atlas, `PROBE_PATTERNS` e `redaction.extra_patterns`) rodam primeiro, no texto original;
  2. depois vêm os literais (o contexto e os valores das credenciais).

  Um contexto curto, como `api`, não pode impedir que `api_key=<valor>` seja mascarado.
- **Variantes do contexto e das credenciais:** a máscara literal pega também, sem diferença de maiúsculas, a forma escapada em JSON (inclusive `\/`) e a forma codificada em URL.
- **Texto que não vira UTF-8:** uma string com surrogate solto na saída do adaptador conta como JSON inválido (exit 1, sem traceback).
- **Clusters do alvo:** cada nome em `target.clusters` segue a regra de nome simples. Uma URL de servidor também vale, desde que sem espaço, sem caractere de controle e sem `-` no começo. Fora disso, é exit 2 antes de rodar qualquer coisa, como os outros campos do alvo (Emenda v4).

**Esclarecimentos (Emenda v6):**
- **Máscara numa passada só:**
  1. todos os padrões de segredo e todos os literais (contexto e valores das credenciais, com as variantes da Emenda v5) procuram casamentos no texto original;
  2. os trechos casados são juntados (união dos intervalos);
  3. cada trecho resultante é trocado uma vez por `[REDACTED]`.

  Assim nenhuma máscara impede a outra, em qualquer ordem: uma senha com cara de e-mail sai inteira mascarada, e `api_key=<valor>` também, com contexto `api`. Esta regra substitui a ordem da Emenda v5.

- **Alcance:** a mesma função passa a servir também a máscara do `scan` e do `lint`, que ficam mais seguros e com os goldens iguais. Por isso o `touches` ganha `skills/boson-atlas/references/redaction.md`.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: o subcomando, a validação de `probes`, o contrato e o resumo.
- `references/probes.md` (nova): contrato, configuração, exits e como escrever um adaptador.
- `references/config.md`: a chave `probes`.
- `SKILL.md`: uma linha sobre o comando e as regras de uso (confirmar produção com a pessoa).
- CHANGELOG, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Sem probes | sem a chave ou `enabled: false` | exit 4; nenhum adaptador roda | CH-01 |
| Configuração | campos válidos e inválidos | aceito; inválido → exit 2 sem o valor | UT-01 |
| Verbo | fora da interseção | exit 4, adaptador não roda | UT-02 |
| Produção | tier production ou sem tier | exit 4 sem `--confirm-production`; roda com ela | UT-03 |
| Acesso | cluster sem `access.clusters` | exit 4 | UT-03 |
| Saída | segredo, excesso de itens, chave desconhecida, JSON inválido, timeout | mascarado; truncado; erro sem saída parcial | UT-04 |
| Registro | qualquer probe | uma linha local sem resultado; nada no atlas | UT-05 |
| Resumo | linhas de log com números e ids variando | assinaturas agrupadas e contadas | UT-06 |
| Ponta a ponta | adaptador falso real como processo | saída, registro e exits certos | IT-01 |
| Contrato | `--describe`, entrada e saída | validados contra `probe@1` | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dada uma configuração sem a chave `probes` (ou com `enabled: false`), quando qualquer comando de hoje roda, então nada muda. `probe` sai com 4, "probes desligadas", sem executar nenhum processo (guarda: os comandos de hoje passam antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `probes` com adaptador, verbos, timeout e credenciais válidos, então `config --json` mostra a configuração sem valores de credencial. Os casos inválidos dão exit 2 com `probes: <campo> inválido — <motivo>`, sem o valor:
  - timeout fora de 1..300;
  - `lines` fora de 1..2000;
  - verbo com espaço;
  - credencial com valor.
- **UT-02** — Dado um adaptador que declara `runtime: [status, logs]` e uma configuração que libera `[status]`, quando `probe runtime logs` roda, então sai com 4, "verbo logs não permitido", e o adaptador não roda (registro de processos do dublê vazio). O mesmo vale para `probe runtime delete`.
- **UT-03** — Para um ambiente `tier: production`, e também para um ambiente sem tier, `probe` sem `--confirm-production` sai com 4 e a mensagem do contrato, e com a opção roda e registra `confirmed_production: true`. Num ambiente `tier: test`, roda sem a opção. Um cluster sem `access.clusters` sai com 4.
- **UT-04** — Dado um adaptador que devolve:
  - uma linha com `token=ghp_...` e um e-mail;
  - 500 itens com `--lines 50`;
  - uma chave fora do contrato;
  - JSON inválido;
  - ou demora mais que o timeout,

  então o token e o e-mail saem mascarados e a saída fica com 50 itens e `truncated: true`. Chave desconhecida, JSON inválido e timeout dão exit 1 com o motivo, sem nenhum item impresso. O `message` de erro também é mascarado.
- **UT-05** — Depois de probes com sucesso, com erro e recusadas, o `probes.log` local tem uma linha por probe com as chaves do contrato e sem `items`, `message` nem o contexto. Nenhum arquivo da pasta do atlas muda (hash da árvore antes e depois).
- **UT-06** — Dadas as linhas `ERROR user 123 not found`, `ERROR user 456 not found`, `WARN retry 3 of 5` e `ERROR id 5f2b...-uuid failed`, quando `--summary` roda, então há duas assinaturas de erro (`ERROR user <n> not found` × 2 e a do UUID) e uma de aviso, com contagem, primeiro e último horário.

### 7.3 Testes de Integração
- **IT-01** — Com um adaptador falso de verdade (script Python em `tests/fixtures/fake-probes/`) e um atlas temporário com o mapa de acesso, quando `atlas.py probe runtime status --service api --env dev --json` roda como processo, então a saída segue o contrato, o registro tem uma linha e as credenciais declaradas chegam ao adaptador só pelos nomes configurados.

### 7.4 Testes de Contrato
- **CT-01** — Dados exemplos de `--describe`, entrada e saída de `probe@1` (válidos e inválidos), quando o validador do núcleo roda, então os válidos passam e cada inválido é recusado com o motivo. `references/probes.md` traz os mesmos exemplos (o teste os lê do documento).

### 7.5 Testes E2E
- N/A — sem jornada interativa. IT-01 roda a CLI como processo, e a jornada de verificação é da SPEC-0090.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Adaptadores falsos em `tests/fixtures/fake-probes/` (ok, erro, lento, saída inválida, eco das credenciais por nome).
- Configuração e atlas temporários.
- Sem rede e sem cluster.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. A funcionalidade vem desligada (`probes.enabled: false`).
- **Dados/schema:** chave local nova e um arquivo de registro local. Nada no atlas.
- **Compatibilidade:** é aditiva. A versão anterior não tem o subcomando e ignora a chave local.
- **Observabilidade:** o registro local e as linhas do `doctor`.
- **Rollback:** `probes.enabled: false` ou reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde fica a configuração das probes? — No `config.yml` local, junto das credenciais por nome, porque é a máquina que tem o acesso (ADR-0023; recomendação do arquiteto, revisável no H1).
- [x] Ambiente sem marcação pode receber probe sem confirmação? — Não. Conta como produção (ADR-0023; recomendação do arquiteto, revisável no H1).
- [x] O resumo de logs fica no núcleo ou no adaptador? — No núcleo, para valer igual em qualquer adaptador de logs e ser usado pelo `verify` (recomendação do arquiteto; revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [x] Red: CH-01 (passa antes), UT-01 a UT-06, IT-01 e CT-01 com a tag `SPEC-0088:<ID>`, falhando pelo motivo certo; adaptadores falsos em `tests/fixtures/fake-probes/` (ok, erro, lento, saída inválida, eco das credenciais por nome)
- [x] Green: comando `probe` no `atlas.py` (contrato `probe@1`, verbos permitidos, produção confirmada, limites, redação, `--summary`, registro `probes.log` sem resultados), chave local `probes` validada, `references/probes.md`, `references/config.md`, `SKILL.md`, `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c2bbfa3 | 2026-11-22 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=49, skipped=1)) — 677c563 | 2026-11-23 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 4f9feb8 | 2026-11-23 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — df49b5d | 2026-11-23 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente (subagente, rodada 4): APPROVED — rodadas 2 e 3 também APPROVED, com minors corrigidos nas Emendas v5 e v6; ficam 2 minors que já existiam na main (tokens colados na alternância do SECRET_RE; regex url/jwt quadráticas em entrada hostil), na SPEC nova de robustez da máscara — 692c1a4 | 2026-11-23 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-23 — reviewer independente (subagente, rodada 1): REJECTED — major M1: o contexto do kubeconfig vaza quando o adaptador o ecoa (stderr, message, itens); minors: JSON muito aninhado dá traceback, --summary com zero itens, command relativo, campos do alvo sem restrição; nits: NaN, doc do ambiente — 8350967
- G4 PASS 2026-11-23 — depois de 1 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- `atlas.py probe <capacidade> <verbo> --service --env` consulta a infraestrutura ao vivo por adaptadores que a máquina declara na configuração local `probes`. Vem desligado por padrão.
- Proteções no núcleo, para qualquer adaptador (ADR-0023):
  - só os verbos que o adaptador declara e a configuração libera;
  - produção ou ambiente sem marcação só com `--confirm-production`;
  - recusa sem acesso local ao cluster;
  - limites de linhas, de janela, de tempo e de bytes;
  - campos do alvo conferidos antes de rodar;
  - saída validada contra `probe@1` e mascarada (segredos, contexto do kubeconfig e valores das credenciais, numa passada só);
  - registro local `probes.log` sem resultados.
- `--summary` resume logs por assinatura. `doctor` mostra o estado das probes e dos adaptadores.

### Como foi feito
- `scripts/atlas.py`:
  - subcomando `probe`; validação `validate_probes`;
  - validadores `validate_probe_describe`, `validate_probe_input` e `validate_probe_output`;
  - `run_collector` ganhou entrada pelo stdin e limite de bytes;
  - `target_problem` e `cluster_problem` conferem o alvo;
  - `_redact_text` agora mascara pela união dos trechos casados no texto original, e o `scan` e o `lint` ficaram mais seguros, com os goldens iguais.
- `references/probes.md`, `references/config.md`, `references/redaction.md` e `SKILL.md`.
- Emendas:
  - v2: perguntas do G1;
  - v3: relatório do implementer;
  - v4: rodada 1 do G4 (contexto vazando quando o adaptador o ecoa, JSON aninhado, `command` relativo, campos do alvo);
  - v5: rodada 2 (ordem da máscara, variantes, surrogate, clusters);
  - v6: rodada 3 (máscara numa passada só).
- G4 aprovado na rodada 4.
- Versões: ATLAS_VERSION 2026.11.15, plugin 2026.11.28.

### Prova de Correção
N/A — type feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Sem `probes` ou desligadas, nada muda e nenhum processo roda (exit 4) | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-01 | Configuração `probes` validada sem mostrar valores; `command` relativo recusado | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-02 | Verbos pela interseção; adaptador ausente; campos do alvo e clusters conferidos antes de rodar | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-03 | Produção e sem marcação exigem `--confirm-production`; sem acesso local, recusa | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-04 | Saída validada, cortada e mascarada numa passada só (contexto, credenciais, variantes); JSON inválido, NaN e surrogate; timeout | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-05 | `probes.log` local, uma linha por probe, sem resultados | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-06 | `--summary` agrupa por nível e assinatura; janela vazia é exit 0 | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| IT-01 | Adaptador falso de verdade: entrada exata, credenciais só por nome, nada vaza | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |
| CT-01 | Exemplos de `probe@1` válidos e inválidos, lidos também do `references/probes.md` | PASS | `test_probe.py` — CI do PR #63 (run 45135256745, Python 3.9 e 3.15) e suíte local no G2/G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy (G6 N/A, mesmo critério da SPEC-0017). A entrega chega pelo plugin `fermion` 2026.11.28, depois do merge do PR #63.

### Pendências
- SPEC-0092 (proposta): tokens colados na alternância do `SECRET_RE` e regex `url`/`jwt` lentas em entrada hostil. Os dois problemas já existiam na `main` e foram achados no G4, rodada 4.
- Radar (sem spec):
  - contexto de 1 ou 2 caracteres mascara demais;
  - `--describe` roda antes das recusas de verbo, produção e acesso, como diz o contrato.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0088`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-23 | Esclarecimentos (Emenda v2): CH-01 em guarda e recusa; nomes do validador e marcação dos exemplos; `ts`/`line` e ordem do `--summary`; credenciais por adaptador; `--describe` no fim; registro das recusas; mensagens | Perguntas do test-writer no G1 | — | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 3 | 2026-11-23 | Esclarecimentos (Emenda v3): linhas do `doctor`; redação a mais só nas probes; ambiente do adaptador por lista permitida; escolha do alvo e do adaptador; `assets/probes/<id>.py` por padrão; status do registro | Relatório do implementer no G2 | SPEC-0089 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 4 | 2026-11-23 | Esclarecimentos (Emenda v4): contexto mascarado na saída do adaptador; JSON aninhado e NaN inválidos; `--summary` vazio é exit 0; `command` relativo recusado; campos do alvo conferidos; doc do ambiente | Achados da rodada 1 do G4 | SPEC-0089 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 5 | 2026-11-23 | Esclarecimentos (Emenda v5): padrões de segredo antes dos literais; variantes do contexto (JSON, URL, maiúsculas); surrogate solto é JSON inválido; clusters do alvo conferidos | Achados minor da rodada 2 do G4 (um deles reabria vazamento de segredo) | SPEC-0089 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 6 | 2026-11-23 | Esclarecimentos (Emenda v6): máscara por união dos trechos casados no texto original, numa passada só, no lugar da ordem da Emenda v5 | Achado minor da rodada 3 do G4 (valor de credencial em parte casado por um padrão vazava o resto) | SPEC-0089 | thomas, 2026-11-23 (piloto automático com o recomendado) |
