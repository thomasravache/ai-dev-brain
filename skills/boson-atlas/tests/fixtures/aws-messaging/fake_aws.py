#!/usr/bin/env python3
"""AWS CLI falsa da SPEC-0098 (adaptador aws-messaging): responde só as operações de leitura da lista fechada da
seção 6, com um cenário em JSON, registra cada argv e recusa qualquer outra. Só biblioteca padrão; nenhuma nuvem,
nenhuma rede, nenhum ~/.aws.

Os testes copiam este arquivo como `aws` para uma pasta temporária (no PATH), com o cabeçalho trocado pelo Python dos
testes. O cenário fica ao lado da cópia, em `fake-aws.json` (o núcleo do probe só passa ao adaptador uma base fixa de
variáveis, então o dublê não depende do ambiente):
    {"record": "<arquivo .jsonl>", "account": "123456789012", "partition": "aws",
     "queues": {"<nome>": {<atributo>: "<valor em texto>"}},          atributos como a SQS devolve (texto)
     "metrics": {"<nome da fila>": [<valor mais recente>, ...]},      pontos de ApproximateAgeOfOldestMessage
     "topics": {"<nome>": [<item de list-subscriptions-by-topic>]},
     "subscriptions": {"<ARN da assinatura>": {<atributo>: "<valor>"}},
     "fail": [{"mode": "<modo>", "service": "<serviço>"?, "operation": "<operação>"?, "name": "<fila|tópico>"?}]}

- `record`: cada chamada vira uma linha JSON {"argv": [...], "allowed": true|false}.
- Modos de `fail` (texto parecido com o da CLI real, com o profile, a conta, o ARN e a URL, para provar que o
  adaptador não os repete): sso-expired, token-expired, profile-not-found, no-credentials, denied (AccessDenied, ou
  AuthorizationError no sns), throttling, no-connection, timeout (Read timeout), invalid-json (exit 0 com JSON
  quebrado), wrong-shape (exit 0 com JSON de outra forma), fail (erro livre, exit 255).
- Fila inexistente: QueueDoesNotExist ("The specified queue does not exist"); tópico ou assinatura inexistente,
  ou ARN de tópico com outra conta: NotFound.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-aws.json").read_text(encoding="utf-8"))
ACCOUNT = SCENARIO.get("account", "123456789012")
PARTITION = SCENARIO.get("partition", "aws")
ALLOWED = {("sqs", "get-queue-url"), ("sqs", "get-queue-attributes"), ("cloudwatch", "get-metric-data"),
           ("sts", "get-caller-identity"), ("sns", "list-subscriptions-by-topic"),
           ("sns", "get-subscription-attributes")}
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


def resource_name(service, operation, options):
    if operation == "get-queue-url":
        return options.get("--queue-name")
    if operation == "get-queue-attributes":
        url = options.get("--queue-url")
        return url.rsplit("/", 1)[-1] if isinstance(url, str) else None
    if operation == "list-subscriptions-by-topic":
        arn = options.get("--topic-arn")
        return arn.rsplit(":", 1)[-1] if isinstance(arn, str) else None
    if operation == "get-metric-data":
        return metric_queue(options)
    return None


def failure(service, operation, name):
    for rule in SCENARIO.get("fail") or []:
        if rule.get("service") not in (None, service):
            continue
        if rule.get("operation") not in (None, operation):
            continue
        if rule.get("name") not in (None, name):
            continue
        return rule["mode"]
    return ""


def simulate(mode, service, operation, region, profile):
    op = camel(operation)
    arn = f"arn:{PARTITION}:{service}:{region}:{ACCOUNT}:orders"
    url = f"https://{service}.{region}.amazonaws.com/{ACCOUNT}/orders"
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
        code = "AuthorizationError" if service == "sns" else "AccessDenied"
        die(f"\nAn error occurred ({code}) when calling the {op} operation: User: "
            f"arn:{PARTITION}:sts::{ACCOUNT}:assumed-role/{profile}/session is not authorized to perform: "
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


def queue_url(region, name):
    return f"https://sqs.{region}.amazonaws.com/{ACCOUNT}/{name}"


def no_queue(op):
    die(f"\nAn error occurred (QueueDoesNotExist) when calling the {op} operation: The specified queue does not "
        "exist.\n", 254)


def not_found(op, what):
    die(f"\nAn error occurred (NotFound) when calling the {op} operation: {what} does not exist\n", 254)


def metric_queue(options):
    raw = options.get("--metric-data-queries")
    try:
        queries = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(queries, list) or len(queries) != 1 or not isinstance(queries[0], dict):
        return None
    metric = ((queries[0].get("MetricStat") or {}).get("Metric") or {})
    for dimension in metric.get("Dimensions") or []:
        if isinstance(dimension, dict) and dimension.get("Name") == "QueueName":
            return dimension.get("Value")
    return None


def answer(service, operation, options, region):
    queues = SCENARIO.get("queues") or {}
    if operation == "get-queue-url":
        name = options.get("--queue-name")
        if name not in queues:
            no_queue("GetQueueUrl")
        return {"QueueUrl": queue_url(region, name)}
    if operation == "get-queue-attributes":
        url = options.get("--queue-url")
        name = url.rsplit("/", 1)[-1] if isinstance(url, str) else None
        if not isinstance(url, str) or url != queue_url(region, name) or name not in queues:
            no_queue("GetQueueAttributes")
        names = options.get("--attribute-names")
        names = [names] if isinstance(names, str) else list(names or [])
        attributes = queues[name]
        if "All" in names:
            return {"Attributes": dict(attributes)}
        return {"Attributes": {key: value for key, value in attributes.items() if key in names}}
    if operation == "get-metric-data":
        name = metric_queue(options)
        values = list((SCENARIO.get("metrics") or {}).get(name) or [])
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        stamps = [(now - timedelta(minutes=i + 1)).strftime("%Y-%m-%dT%H:%M:%S+00:00") for i in range(len(values))]
        values = [float(v) for v in values]
        if options.get("--scan-by") == "TimestampAscending":
            stamps, values = stamps[::-1], values[::-1]
        return {"MetricDataResults": [{"Id": "age", "Label": "ApproximateAgeOfOldestMessage", "Timestamps": stamps,
                                       "Values": values, "StatusCode": "Complete"}], "Messages": []}
    if operation == "get-caller-identity":
        return {"UserId": "AROAEXAMPLEEXAMPLE:session", "Account": ACCOUNT,
                "Arn": f"arn:{PARTITION}:sts::{ACCOUNT}:assumed-role/acme-read/session"}
    if operation == "list-subscriptions-by-topic":
        arn = options.get("--topic-arn")
        topics = SCENARIO.get("topics") or {}
        name = arn.rsplit(":", 1)[-1] if isinstance(arn, str) else None
        if arn != f"arn:{PARTITION}:sns:{region}:{ACCOUNT}:{name}" or name not in topics:
            not_found("ListSubscriptionsByTopic", "Topic")
        return {"Subscriptions": topics[name]}
    if operation == "get-subscription-attributes":
        arn = options.get("--subscription-arn")
        table = SCENARIO.get("subscriptions") or {}
        if not isinstance(arn, str) or arn not in table:
            not_found("GetSubscriptionAttributes", "Subscription")
        return {"Attributes": table[arn]}
    return None


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
    mode = failure(service, operation, resource_name(service, operation, options))
    if mode:
        simulate(mode, service, operation, region, profile)
    print(json.dumps(answer(service, operation, options, region), indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
