# Verify — foto antes do merge, comparação depois do deploy e veredito

`atlas.py verify` responde, com evidência, se uma entrega chegou e está saudável num ambiente (ADR-0024, SPEC-0090). Tem duas fases, as duas **só de leitura** e feitas pelas probes (`references/probes.md`):

- **`snapshot`**, antes do merge: grava uma foto do serviço no ambiente num **arquivo da tarefa**, fora do atlas;
- **`compare`**, depois do deploy: compara o estado de agora com a foto e com a imagem esperada e dá um veredito: `passou`, `degradou` ou `inconclusivo`.

O `verify` não roda adaptador por conta própria: cada consulta passa pelo mesmo caminho do `probe` (ligadas, verbos permitidos, produção confirmada, acesso local, saída validada e mascarada, uma linha em `probes.log`). Nada é gravado no atlas, e nenhuma ação é executada no ambiente, nem rollback.

## Pré-requisitos

- As probes ligadas nesta máquina (`probes.enabled: true`), com um adaptador da capacidade `runtime` que libere `status`, `events` e `logs` (o `kubernetes` da skill serve: `references/probes/kubernetes.md`).
- O serviço com deployment no ambiente no atlas (`scan` e `build`) e o cluster dele em `access.clusters`.

## `verify snapshot`

```text
atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo>
    [--since 30m] [--confirm-production] [--atlas X]
```

Para **cada** deployment do serviço no ambiente roda três probes: `runtime status`, `runtime events` e `runtime logs --summary` (os eventos e os logs na janela `--since`, padrão `30m`, até `24h`). Grava em `--out`:

- `images` — as imagens dos pods, como o adaptador as dá (caminho sem o host do registry, com tag e digest);
- `ready` e `desired` — réplicas prontas e desejadas, somadas pelos workloads;
- `restarts` — restarts por pod;
- `warnings` — os eventos de alerta como `<motivo>|<Kind>/<nome>`, com o nome do pod trocado pelo workload dono (`BackOff` em `api-7f9c-aaaa` ou em `api-7f9c-bbbb` é o mesmo `BackOff|Pod/api`);
- `error_signatures` — só as assinaturas de nível `error` do `--summary`, com a contagem;
- `not_verified` — cada verificação que a foto não conseguiu sustentar, com o motivo (probe recusada, com erro ou que falhou; logs cortados sem nenhuma linha = "nenhum pod respondeu").

A foto **não guarda nenhuma linha de log**, nem mascarada, nem amostra: só assinaturas e contagens, já com a redaction. Ela é um arquivo da tarefa: quem chama apaga o arquivo no fim (SPEC-0091).

`--out` precisa ficar **fora da pasta do atlas**: o caminho é resolvido (com `..` e links) antes de qualquer probe, e dentro do atlas sai com 2 sem gravar nada. A pasta de `--out` precisa existir.

Exemplo de foto (`verify@1`):

```json
{
  "contract": "verify@1",
  "service": "api",
  "environment": "dev",
  "taken_at": "2026-11-23T09:00:00Z",
  "deployments": {
    "dev-api": {
      "images": ["acme/api:1.4.1@sha256:0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b"],
      "ready": 3,
      "desired": 3,
      "restarts": {"api-7f9c-aaaa": 0, "api-7f9c-bbbb": 1, "api-7f9c-cccc": 0},
      "warnings": ["BackOff|Pod/api"],
      "error_signatures": {"ERROR user <n> not found": 2}
    }
  },
  "not_verified": []
}
```

Chaves fechadas: uma chave a mais, `contract` diferente de `verify@1` ou um tipo errado fazem o `compare` recusar a foto (exit 2).

## `verify compare`

```text
atlas.py verify compare --service <id> --env <ambiente> --expect-image <imagem>
    [--baseline <arquivo>] [--window 10m] [--max-new-errors 0] [--max-new-restarts 0]
    [--confirm-production] [--json] [--atlas X]
```

- `--expect-image` — o caminho normalizado da imagem (sem o host do registry) com `:<tag>`, `@<digest>` ou os dois: `acme/api:1.4.2`, `acme/api@sha256:…`. Sem tag nem digest sai com 2.
- `--baseline` — a foto do `snapshot`, do mesmo serviço e ambiente. Ausente, que não é JSON ou fora do contrato sai com 2. Sem ela, os logs ficam não verificados.
- `--window` — a janela dos eventos e dos logs (padrão `10m`, até `24h`).
- `--max-new-errors` e `--max-new-restarts` — o que se tolera (padrão `0` e `0`, conservadores).

Roda as mesmas três probes por deployment e faz três verificações em cada um:

| Verificação | `ok` quando | `failed` quando | `not_verified` quando |
|---|---|---|---|
| `delivery` | o rollout terminou e **todo** pod pronto roda a imagem esperada (pelo digest, se dado; senão pela tag) | um pod pronto com outra imagem (o pod e as imagens dele na evidência), rollout não concluído, nenhum pod pronto ou workload não encontrado | a probe de `status` foi recusada, falhou ou respondeu com erro |
| `runtime` | nenhum pod não pronto, os restarts novos somados ≤ `--max-new-restarts` e nenhum aviso novo | pod não pronto, restarts novos acima do limite, aviso (`<motivo>\|<objeto>`) que não estava na foto ou workload não encontrado (`found: false`) | a probe de `status` (ou só a de `events`, sem outra falha) foi recusada, falhou ou respondeu com erro |
| `logs` | as assinaturas de erro da janela que não estavam na foto são ≤ `--max-new-errors` | assinaturas novas acima do limite (as novas na evidência) | sem `--baseline` ("sem foto de antes: erros novos e antigos não se separam"); a foto não tem os logs do deployment; logs cortados sem nenhuma linha ("nenhum pod respondeu"); probe recusada, com erro ou que falhou |

- **Restarts novos** = os de agora menos os da foto, por pod; um pod que não estava na foto (por exemplo depois do rollout) conta desde 0. Sem foto, todos contam.
- **Avisos novos** = as chaves `<motivo>|<objeto>` que não estavam na foto; sem foto, todos contam.
- **Assinaturas** = só as de nível `error` do `--summary` (`warn` e `info` não contam).

### Veredito e exits

- `degradou` (exit 1) se alguma verificação deu `failed`;
- senão `inconclusivo` (exit 5) se alguma ficou `not_verified`;
- senão `passou` (exit 0).

Uma verificação que não foi feita nunca vira `passou`. Em `degradou`, sai uma **sugestão**: um texto fixo pedindo que a pessoa decida o rollback, citando o repositório de configuração do delivery (o `sourced_from` do deployment no atlas). Ela nunca traz comando, e nada é executado.

Outros exits: 2 argumento inválido (inclusive `--out` dentro do atlas, `--expect-image` sem tag nem digest, `--baseline` inválida, `--window` ou limite fora do formato), 3 sem configuração, 4 probes desligadas ou produção sem `--confirm-production`. Uma probe recusada (verbo, sem acesso, sem adaptador) ou com falha **não** dá 4 nem 1: a verificação dela fica `not_verified`.

### Produção

Segue a regra das probes (ADR-0023): ambiente `tier: production` ou sem `tier` só com `--confirm-production`, depois do "sim" da pessoa na conversa. Sem a opção, `snapshot` e `compare` saem com 4 antes de qualquer consulta, e a foto não é gravada. Em produção o `verify` é só passivo, como sempre.

### Saída

Sem `--json`, Markdown: o veredito, uma tabela com cada verificação e o motivo, as evidências e a sugestão. Com `--json`, o objeto `verify@1` com as chaves fechadas `contract`, `verdict`, `checks` e `suggestion` (vazia fora de `degradou`); cada verificação tem `deployment`, `check`, `status`, `evidence` e `reason` (obrigatório em `not_verified`):

```json
{
  "contract": "verify@1",
  "verdict": "degradou",
  "checks": [
    {"deployment": "dev-api", "check": "delivery", "status": "ok",
     "evidence": {"expected": "acme/api:1.4.2", "rollout_complete": true, "ready_pods": 3, "pods_with_other_image": [], "workloads_not_found": []},
     "reason": "3 pod(s) pronto(s) com acme/api:1.4.2"},
    {"deployment": "dev-api", "check": "runtime", "status": "failed",
     "evidence": {"workloads_not_found": [], "not_ready_pods": ["api-7c2d-cccc"], "new_restarts": {"api-7c2d-cccc": 4}, "new_restarts_total": 4, "max_new_restarts": 0, "baseline": "foto", "new_warnings": ["BackOff|Pod/api"]},
     "reason": "1 pod(s) não pronto(s); 4 restart(s) novo(s), acima de 0; 1 aviso(s) novo(s)"},
    {"deployment": "dev-api", "check": "logs", "status": "failed",
     "evidence": {"window_seconds": 600, "max_new_errors": 0, "new_error_signatures": {"ERROR timeout calling <texto>": 1}, "known_error_signatures": 1, "truncated": false},
     "reason": "1 assinatura(s) de erro nova(s), acima de 0"}
  ],
  "suggestion": "Degradou: mostre as evidências à pessoa e deixe que ela decida se volta a versão anterior. O rollback, se ela decidir, é feito no repositório de configuração do delivery (acme/iac), pelo fluxo de mudança do time. O verify não executa nenhuma ação no ambiente."
}
```

## Validadores

`atlas.py` tem `validate_verify_snapshot(data)` e `validate_verify_result(data)`, que devolvem a lista de problemas (`[]` = válido). O `snapshot` só grava uma foto válida, o `compare` só aceita uma `--baseline` válida e só imprime um resultado válido.

## Uso típico (G6 da gluon-spec)

1. Antes do merge: `verify snapshot --service api --env dev --out <pasta da tarefa>/foto.json`.
2. Depois que o roteiro de verificação (SPEC-0086) mostra a imagem nova no repositório de configuração: `verify compare --service api --env dev --baseline <pasta da tarefa>/foto.json --expect-image acme/api:1.4.2 --json`.
3. Leve o veredito e as evidências ao Relatório de Entrega; em `degradou`, mostre a sugestão e deixe a pessoa decidir. Se o rollout ainda não terminou, repita depois da janela.
4. Apague a foto no fim da tarefa.
