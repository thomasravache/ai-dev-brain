#!/usr/bin/env python3
"""AWS CLI falsa (SPEC-0097): responde `aws <serviço> <operação> --region <r> ...` com respostas gravadas, sem rede
e sem ler ~/.aws. Só biblioteca padrão.

Os testes copiam este arquivo como `aws` para uma pasta no início do PATH. Variáveis:
- FAKE_AWS_RESPONSES: pasta do cenário (padrão: responses/acme, ao lado deste arquivo). A resposta de uma operação
  de lista é <cenário>/<região>/<serviço>-<operação>.json; sem o arquivo, a lista vem vazia. `sqs
  get-queue-attributes` e `sns get-subscription-attributes` leem um mapa {URL da fila | ARN da assinatura:
  resposta}; uma URL ou um ARN fora do mapa falha como a CLI real (NonExistentQueue / NotFound, exit 254).
- FAKE_AWS_LOG: arquivo onde cada chamada é anotada, uma linha JSON {"argv": [...], "env": [nomes das variáveis
  recebidas], "aws_profile": valor de AWS_PROFILE ou null} (o valor do profile só aparece neste registro do teste).
- FAKE_AWS_MODE: erro simulado, com o texto parecido com o da CLI real (que traz o profile e a conta, para provar
  que o coletor não os repete). Forma <modo>[:<serviço>[:<operação>]]: sem serviço vale para toda chamada; com
  serviço (e operação), só para ela. Modos: no-credentials, sso-expired, token-expired, profile-not-found,
  denied, slow (Read timeout), invalid-json, fail (código 255 com texto livre), next-token (resposta com NextToken).

--max-items N corta a lista em N e devolve NextToken quando sobrava item, como a CLI real.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCOUNT = "123456789012"
LIST_KEYS = {
    ("rds", "describe-db-clusters"): "DBClusters",
    ("rds", "describe-db-instances"): "DBInstances",
    ("elasticache", "describe-replication-groups"): "ReplicationGroups",
    ("elasticache", "describe-cache-clusters"): "CacheClusters",
    ("elasticache", "describe-serverless-caches"): "ServerlessCaches",
    ("sqs", "list-queues"): "QueueUrls",
    ("sns", "list-topics"): "Topics",
    ("sns", "list-subscriptions"): "Subscriptions",
}
GET_KEYS = {("sqs", "get-queue-attributes"): "--queue-url",
            ("sns", "get-subscription-attributes"): "--subscription-arn"}
FLAGS = {"--no-cli-pager", "--show-cache-node-info", "--debug", "--no-paginate"}


def camel(operation):
    return "".join(part.capitalize() for part in operation.split("-"))


def log(argv):
    path = os.environ.get("FAKE_AWS_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "env": sorted(os.environ),
                                     "aws_profile": os.environ.get("AWS_PROFILE")}) + "\n")


def parse(argv):
    """(serviço, operação, {opção: valor}) de `aws <serviço> <operação> [--opção valor | --flag]...`."""
    positional, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            if arg in FLAGS or i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                options[arg] = True
                i += 1
            else:
                options[arg] = argv[i + 1]
                i += 2
        else:
            positional.append(arg)
            i += 1
    service, operation = (positional + ["", ""])[:2]
    return service, operation, options


def die(text, code):
    sys.stderr.write(text)
    sys.exit(code)


def mode_for(service, operation):
    raw = os.environ.get("FAKE_AWS_MODE", "")
    if not raw:
        return ""
    parts = raw.split(":")
    name, scope = parts[0], parts[1:]
    if scope and scope[0] != service:
        return ""
    if len(scope) > 1 and scope[1] != operation:
        return ""
    return name


def simulate(mode, service, operation, region):
    profile = os.environ.get("AWS_PROFILE") or "default"
    op = camel(operation)
    if mode == "no-credentials":
        die('\nUnable to locate credentials. You can configure credentials by running "aws configure".\n', 253)
    if mode == "sso-expired":
        die(f"\nError when retrieving token from sso: Token has expired and refresh failed\n"
            f"The SSO session associated with this profile ({profile}) has expired or is otherwise invalid. To "
            f"refresh this SSO session run aws sso login with the corresponding profile.\n", 255)
    if mode == "token-expired":
        die(f"\nAn error occurred (ExpiredToken) when calling the {op} operation: The security token included in "
            f"the request is expired (profile {profile}, account {ACCOUNT})\n", 254)
    if mode == "profile-not-found":
        die(f"\nThe config profile ({profile}) could not be found\n", 255)
    if mode == "denied":
        die(f"\nAn error occurred (AccessDeniedException) when calling the {op} operation: User: "
            f"arn:aws:sts::{ACCOUNT}:assumed-role/{profile}/session is not authorized to perform: "
            f"{service}:{op} on resource: arn:aws:{service}:{region}:{ACCOUNT}:*\n", 254)
    if mode == "slow":
        die(f'\nRead timeout on endpoint URL: "https://{service}.{region}.amazonaws.com/{ACCOUNT}/orders"\n', 255)
    if mode == "invalid-json":
        sys.stdout.write(f'{{"broken": "arn:aws:{service}:{region}:{ACCOUNT}:x"\n')
        sys.exit(0)
    if mode == "fail":
        die(f"\nsomething odd happened for {profile} in account {ACCOUNT} at "
            f"https://{service}.{region}.amazonaws.com/{ACCOUNT}/orders\n", 255)


def scenario():
    return Path(os.environ.get("FAKE_AWS_RESPONSES") or HERE / "responses" / "acme")


def main(argv):
    log(argv)
    service, operation, options = parse(argv)
    region = options.get("--region") or os.environ.get("AWS_REGION") or ""
    if not region:
        die("\nYou must specify a region. You can also configure your region by running \"aws configure\".\n", 253)
    mode = mode_for(service, operation)
    if mode and mode != "next-token":
        simulate(mode, service, operation, region)
    folder = scenario() / region
    if (service, operation) in LIST_KEYS:
        key = LIST_KEYS[(service, operation)]
        path = folder / f"{service}-{operation}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {key: []}
        items = data.get(key, [])
        limit = options.get("--max-items")
        if isinstance(limit, str) and limit.isdigit() and len(items) > int(limit):
            data[key] = items[:int(limit)]
            data["NextToken"] = "eyJOZXh0VG9rZW4iOiBudWxsLCAiYm90b190cnVuY2F0ZV9hbW91bnQiOiAyfQ=="
        if mode == "next-token":
            data["NextToken"] = "eyJOZXh0VG9rZW4iOiBudWxsLCAiYm90b190cnVuY2F0ZV9hbW91bnQiOiAyfQ=="
        print(json.dumps(data, indent=4))
        return 0
    if (service, operation) in GET_KEYS:
        option = GET_KEYS[(service, operation)]
        path = folder / f"{service}-{operation}.json"
        table = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        target = options.get(option)
        if not isinstance(target, str) or target not in table:
            code = "AWS.SimpleQueueService.NonExistentQueue" if service == "sqs" else "NotFound"
            die(f"\nAn error occurred ({code}) when calling the {camel(operation)} operation: not found\n", 254)
        print(json.dumps(table[target], indent=4))
        return 0
    die(f"\naws: error: argument operation: Invalid choice: {service} {operation}\n", 252)
    return 252


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
