#!/usr/bin/env python3
"""AWS CLI falsa da SPEC-0100 (adaptador cloudwatch): responde só as operações de leitura da lista fechada da
seção 6 (`cloudwatch get-metric-data` e `elasticache describe-replication-groups`), com um cenário em JSON,
registra cada argv e recusa qualquer outra. Só biblioteca padrão; nenhuma nuvem, nenhuma rede, nenhum ~/.aws.

Os testes copiam este arquivo como `aws` para uma pasta temporária (no PATH), com o cabeçalho trocado pelo Python dos
testes. O cenário fica ao lado da cópia, em `fake-aws.json`:
    {"record": "<arquivo .jsonl>", "account": "123456789012",
     "series": {"<Dimensão>=<valor>/<Métrica>": [<ponto>, ...]},     pontos de qualquer estatística, do mais antigo
     "status": {"<Dimensão>=<valor>/<Métrica>": "Forbidden" | "InternalError" | "PartialData"},
     "pages": <n>,                                                     páginas do get-metric-data (padrão 1)
     "page_status": [{"<Dimensão>=<valor>/<Métrica>": "<StatusCode>"}, ...],  status por página (1ª, 2ª, ...)
     "raw": {"<Dimensão>=<valor>/<Métrica>": "<texto JSON da lista Values>"},  Values crus (NaN, 1e999, ...)
     "groups": {"<id do grupo de replicação>": ["<CacheClusterId>", ...]},
     "fail": [{"mode": "<modo>", "service": "<serviço>"?, "operation": "<operação>"?}]}

- `record`: cada chamada vira uma linha JSON {"argv": [...], "allowed": true|false}.
- get-metric-data: um resultado por consulta, pelo `Id`, com o `Label` igual à métrica; a série é achada pela
  primeira dimensão e pelo nome da métrica do `MetricStat` (sem série = sem pontos, `Complete`); os pontos vêm em
  ordem crescente de tempo, um por `Period`, terminando no `--end-time`. Com `pages` > 1, os pontos de cada série são
  divididos em `pages` blocos contíguos, um por página; cada página traz todas as consultas e, menos a última, um
  `NextToken` ("page-2", "page-3", ...) que a próxima chamada manda em `--next-token`. Uma consulta sem `MetricStat`
  (ex.: `Expression`) faz o dublê falhar (exit 254).
- Com `status` Forbidden ou InternalError, a série sai sem pontos e com uma mensagem que cita a conta.
- `page_status` (SPEC-0100, Emenda v2): o item i vale para a página i+1 e, para as séries que cita, troca o `status`
  só naquela página (ex.: `PartialData` nas intermediárias e `Complete` na última).
- `raw`: a lista `Values` daquela série sai com o texto JSON dado, sem passar por float (para `NaN`, `Infinity`,
  `1e999` ou um inteiro de 400 dígitos); `Timestamps` sai vazio.
- describe-replication-groups: o grupo de `groups` com `MemberClusters` e `NodeGroups[].NodeGroupMembers[]` (e um
  ARN com a conta); grupo ausente = ReplicationGroupNotFoundFault (exit 254).
- Modos de `fail` (texto parecido com o da CLI real, com o profile, a conta e o ARN, para provar que o adaptador não
  os repete): sso-expired, token-expired, profile-not-found, no-credentials, denied (AccessDenied), throttling,
  no-connection, timeout (Read timeout), invalid-json (exit 0 com JSON quebrado), wrong-shape (exit 0 com JSON de
  outra forma), fail (erro livre, exit 255).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-aws.json").read_text(encoding="utf-8"))
ACCOUNT = SCENARIO.get("account", "123456789012")
ALLOWED = {("cloudwatch", "get-metric-data"), ("elasticache", "describe-replication-groups")}
RAW_MARK = "@@raw-values@@"
FLAGS = {"--no-cli-pager", "--debug", "--no-paginate", "--no-verify-ssl", "--no-sign-request"}


def camel(operation):
    return "".join(part.capitalize() for part in operation.split("-"))


def parse(argv):
    """(palavras, {opção: valor | [valores] | True}) de `aws <serviço> <operação> [--opção valor...]...`."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if eq:
                options[name] = value
                i += 1
                continue
            values = []
            i += 1
            while i < len(argv) and not argv[i].startswith("--") and name not in FLAGS:
                values.append(argv[i])
                i += 1
            options[name] = True if not values else values[0] if len(values) == 1 else values
        else:
            words.append(arg)
            i += 1
    return words, options


def record(argv, allowed):
    path = SCENARIO.get("record")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "allowed": allowed}) + "\n")


def die(text, code):
    sys.stderr.write(text)
    sys.exit(code)


def failure(service, operation):
    for rule in SCENARIO.get("fail") or []:
        if rule.get("service") not in (None, service):
            continue
        if rule.get("operation") not in (None, operation):
            continue
        return rule["mode"]
    return ""


def simulate(mode, service, operation, region, profile):
    op = camel(operation)
    arn = f"arn:aws:{service}:{region}:{ACCOUNT}:orders"
    url = f"https://{service}.{region}.amazonaws.com/"
    if mode == "sso-expired":
        die(f"\nError when retrieving token from sso: Token has expired and refresh failed\n"
            f"The SSO session associated with this profile ({profile}) has expired or is otherwise invalid. To "
            f"refresh this SSO session run aws sso login with the corresponding profile.\n", 255)
    if mode == "token-expired":
        die(f"\nAn error occurred (ExpiredToken) when calling the {op} operation: The security token included in "
            f"the request is expired (profile {profile}, {arn})\n", 254)
    if mode == "profile-not-found":
        die(f"\nThe config profile ({profile}) could not be found\n", 255)
    if mode == "no-credentials":
        die('\nUnable to locate credentials. You can configure credentials by running "aws configure".\n', 253)
    if mode == "denied":
        die(f"\nAn error occurred (AccessDenied) when calling the {op} operation: User: "
            f"arn:aws:sts::{ACCOUNT}:assumed-role/{profile}/session is not authorized to perform: "
            f"{service}:{op} on resource: {arn} because no identity-based policy allows the action\n", 254)
    if mode == "throttling":
        die(f"\nAn error occurred (Throttling) when calling the {op} operation (reached max retries: 2): Rate "
            f"exceeded for {arn}\n", 254)
    if mode == "no-connection":
        die(f'\nCould not connect to the endpoint URL: "{url}"\n', 255)
    if mode == "timeout":
        die(f'\nRead timeout on endpoint URL: "{url}"\n', 255)
    if mode == "invalid-json":
        sys.stdout.write(f'{{"broken": "{arn}"\n')
        sys.exit(0)
    if mode == "wrong-shape":
        print(json.dumps({"Unexpected": [arn, url]}))
        sys.exit(0)
    die(f"\nsomething odd happened for {profile} in account {ACCOUNT} at {url} ({arn})\n", 255)


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        die("\nAn error occurred (ValidationError) when calling the GetMetricData operation: invalid time\n", 254)


def series_key(stat):
    metric = stat.get("Metric") or {}
    dimensions = metric.get("Dimensions") or [{}]
    first = dimensions[0] if isinstance(dimensions[0], dict) else {}
    return f"{first.get('Name')}={first.get('Value')}/{metric.get('MetricName')}"


def chunk(values, page, pages):
    n = len(values)
    return values[page * n // pages:(page + 1) * n // pages]


def metric_data(options, region):
    try:
        queries = json.loads(options.get("--metric-data-queries") or "")
    except (TypeError, ValueError):
        die("\nAn error occurred (ValidationError) when calling the GetMetricData operation: bad queries\n", 254)
    if not isinstance(queries, list):
        die("\nAn error occurred (ValidationError) when calling the GetMetricData operation: bad queries\n", 254)
    end = parse_time(options.get("--end-time"))
    pages = int(SCENARIO.get("pages") or 1)
    token = options.get("--next-token")
    page = int(token.split("-", 1)[1]) - 1 if isinstance(token, str) and token.startswith("page-") else 0
    series, statuses = SCENARIO.get("series") or {}, SCENARIO.get("status") or {}
    results = []
    for query in queries:
        stat = query.get("MetricStat") if isinstance(query, dict) else None
        if not isinstance(stat, dict):
            die("\nAn error occurred (ValidationError) when calling the GetMetricData operation: the fake only "
                "answers MetricStat\n", 254)
        key = series_key(stat)
        period = int(stat.get("Period") or 60)
        status = statuses.get(key, "Complete")
        page_status = SCENARIO.get("page_status") or []
        if page < len(page_status) and key in (page_status[page] or {}):
            status = page_status[page][key]
        values = [] if status in ("Forbidden", "InternalError") else [float(v) for v in series.get(key) or []]
        stamps = [(end - timedelta(seconds=period * (len(values) - i))).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                  for i in range(len(values))]
        values, stamps = chunk(values, page, pages), chunk(stamps, page, pages)
        if options.get("--scan-by") == "TimestampDescending":
            values, stamps = values[::-1], stamps[::-1]
        if key in (SCENARIO.get("raw") or {}):
            values, stamps = RAW_MARK + key, []
        result = {"Id": query.get("Id"), "Label": (stat.get("Metric") or {}).get("MetricName"),
                  "Timestamps": stamps, "Values": values, "StatusCode": status}
        if status in ("Forbidden", "InternalError"):
            result["Messages"] = [{"Code": status, "Value": f"not authorized for arn:aws:cloudwatch:{region}:"
                                                            f"{ACCOUNT}:metric/{key}"}]
        results.append(result)
    answer = {"MetricDataResults": results, "Messages": []}
    if page + 1 < pages:
        answer["NextToken"] = f"page-{page + 2}"
    return answer


def replication_groups(options, region):
    gid = options.get("--replication-group-id")
    groups = SCENARIO.get("groups") or {}
    if not isinstance(gid, str) or gid not in groups:
        die(f"\nAn error occurred (ReplicationGroupNotFoundFault) when calling the DescribeReplicationGroups "
            f"operation: ReplicationGroup {gid} not found.\n", 254)
    nodes = list(groups[gid])
    members = [{"CacheClusterId": node, "CacheNodeId": "0001", "CurrentRole": "primary" if i == 0 else "replica",
                "PreferredAvailabilityZone": f"{region}a"} for i, node in enumerate(nodes)]
    return {"ReplicationGroups": [{
        "ReplicationGroupId": gid, "Description": "acme", "Status": "available", "MemberClusters": nodes,
        "NodeGroups": [{"NodeGroupId": "0001", "Status": "available", "NodeGroupMembers": members}],
        "ClusterEnabled": False, "ARN": f"arn:aws:elasticache:{region}:{ACCOUNT}:replicationgroup:{gid}"}]}


def main(argv):
    words, options = parse(argv)
    service, operation = (words + ["", ""])[:2]
    allowed = (service, operation) in ALLOWED and len(words) == 2
    record(argv, allowed)
    if not allowed:
        die(f"\naws: error: argument operation: chamada fora da lista do dublê: {' '.join(words)}\n", 252)
    region = options.get("--region")
    if not isinstance(region, str) or not region:
        die('\nYou must specify a region. You can also configure your region by running "aws configure".\n', 253)
    profile = options.get("--profile") if isinstance(options.get("--profile"), str) else "default"
    mode = failure(service, operation)
    if mode:
        simulate(mode, service, operation, region, profile)
    if operation == "get-metric-data":
        text = json.dumps(metric_data(options, region), indent=4)
        for key, raw in (SCENARIO.get("raw") or {}).items():
            text = text.replace(json.dumps(RAW_MARK + key), raw)
        print(text)
    else:
        print(json.dumps(replication_groups(options, region), indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
