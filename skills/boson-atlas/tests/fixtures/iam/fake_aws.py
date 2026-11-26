#!/usr/bin/env python3
"""AWS CLI falsa da SPEC-0101 (adaptador iam): responde só as leituras e a simulação da lista fechada da seção 6, com
um cenário em JSON, registra cada argv e as variáveis AWS_* que recebeu, e recusa qualquer outra chamada. Só
biblioteca padrão; nenhuma nuvem, nenhuma rede, nenhum ~/.aws.

Os testes copiam este arquivo como `aws` para uma pasta temporária (no PATH), com o cabeçalho trocado pelo Python dos
testes. O cenário fica ao lado da cópia, em `fake-aws.json`:
    {"record": "<arquivo .jsonl>", "account": "123456789012", "partition": "aws",
     "queues": {"<nome>": {"Policy": "<JSON em texto>"?}},     fila sem "Policy" = sem política de recurso
     "topics": {"<nome>": {"Policy": "<JSON em texto>"?}},
     "roles": ["<nome do papel>", ...],                          papel fora da lista = NoSuchEntity na simulação
     "decisions": {"<ação da API>": "<EvalDecision>"},          padrão "allowed"
     "queue_url": {"<nome>": "<QueueUrl devolvida>"},            troca a URL (resposta inválida da nuvem)
     "queue_arn": {"<nome>": "<QueueArn devolvido>"},            troca o QueueArn
     "fail": [{"mode": "<modo>", "service": "<serviço>"?, "operation": "<operação>"?}]}

- `record`: cada chamada vira uma linha JSON {"argv": [...], "allowed": true|false, "env": {<AWS_*>: <valor>}}.
- Modos de `fail` (texto parecido com o da CLI real, com o profile, a conta, o ARN e o marcador
  SENTINEL-STDERR-0101, para provar que o adaptador não os repete): sso-expired, token-expired, profile-not-found,
  no-credentials, denied (AccessDenied, ou AuthorizationError no sns), nosuchentity, timeout (Read timeout),
  invalid-json (exit 0 com JSON quebrado), fail (erro livre, exit 255).
- Fila inexistente: AWS.SimpleQueueService.NonExistentQueue; tópico inexistente (ou ARN de outra conta): NotFound.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-aws.json").read_text(encoding="utf-8"))
ACCOUNT = SCENARIO.get("account", "123456789012")
PARTITION = SCENARIO.get("partition", "aws")
SENTINEL = "SENTINEL-STDERR-0101"
ALLOWED = {("sts", "get-caller-identity"), ("sqs", "get-queue-url"), ("sqs", "get-queue-attributes"),
           ("sns", "get-topic-attributes"), ("iam", "simulate-principal-policy")}
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
        env = {k: v for k, v in os.environ.items() if k.startswith("AWS_")}
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "allowed": allowed, "env": env}) + "\n")


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


def simulate_failure(mode, service, operation, region, profile):
    op = camel(operation)
    arn = f"arn:{PARTITION}:{service}:{region}:{ACCOUNT}:orders"
    url = f"https://{service}.{region}.amazonaws.com/{ACCOUNT}/orders"
    if mode == "sso-expired":
        die(f"\nError when retrieving token from sso: Token has expired and refresh failed\n"
            f"The SSO session associated with this profile ({profile}) has expired or is otherwise invalid. "
            f"{SENTINEL}\n", 255)
    if mode == "token-expired":
        die(f"\nAn error occurred (ExpiredToken) when calling the {op} operation: The security token included in "
            f"the request is expired (profile {profile}, {arn}) {SENTINEL}\n", 254)
    if mode == "profile-not-found":
        die(f"\nThe config profile ({profile}) could not be found {SENTINEL}\n", 255)
    if mode == "no-credentials":
        die(f'\nUnable to locate credentials. You can configure credentials by running "aws configure". '
            f'{SENTINEL}\n', 253)
    if mode == "denied":
        code = "AuthorizationError" if service == "sns" else "AccessDenied"
        die(f"\nAn error occurred ({code}) when calling the {op} operation: User: "
            f"arn:{PARTITION}:sts::{ACCOUNT}:assumed-role/{profile}/session is not authorized to perform: "
            f"{service}:{op} on resource: {arn} {SENTINEL}\n", 254)
    if mode == "nosuchentity":
        die(f"\nAn error occurred (NoSuchEntity) when calling the {op} operation: The role with name x cannot be "
            f"found ({arn}) {SENTINEL}\n", 254)
    if mode == "timeout":
        die(f'\nRead timeout on endpoint URL: "{url}" {SENTINEL}\n', 255)
    if mode == "invalid-json":
        sys.stdout.write(f'{{"broken": "{arn}"\n')
        sys.exit(0)
    die(f"\nsomething odd happened for {profile} in account {ACCOUNT} at {url} ({arn}) {SENTINEL}\n", 255)


def queue_url(region, name):
    return f"https://sqs.{region}.amazonaws.com/{ACCOUNT}/{name}"


def no_queue(op):
    die(f"\nAn error occurred (AWS.SimpleQueueService.NonExistentQueue) when calling the {op} operation: The "
        f"specified queue does not exist. {SENTINEL}\n", 254)


def not_found(op):
    die(f"\nAn error occurred (NotFound) when calling the {op} operation: Topic does not exist {SENTINEL}\n", 254)


def as_list(value):
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, str) else []


def answer(service, operation, options, region):
    queues = SCENARIO.get("queues") or {}
    if operation == "get-caller-identity":
        return {"UserId": "AROAEXAMPLEEXAMPLE:session", "Account": ACCOUNT,
                "Arn": f"arn:{PARTITION}:sts::{ACCOUNT}:assumed-role/acme-read/session"}
    if operation == "get-queue-url":
        name = options.get("--queue-name")
        if name not in queues:
            no_queue("GetQueueUrl")
        return {"QueueUrl": (SCENARIO.get("queue_url") or {}).get(name, queue_url(region, name))}
    if operation == "get-queue-attributes":
        url = options.get("--queue-url")
        name = url.rsplit("/", 1)[-1] if isinstance(url, str) else None
        if not isinstance(url, str) or url != queue_url(region, name) or name not in queues:
            no_queue("GetQueueAttributes")
        names = as_list(options.get("--attribute-names"))
        attributes = dict(queues[name])
        attributes["QueueArn"] = (SCENARIO.get("queue_arn") or {}).get(
            name, f"arn:{PARTITION}:sqs:{region}:{ACCOUNT}:{name}")
        return {"Attributes": {k: v for k, v in attributes.items() if k in names or "All" in names}}
    if operation == "get-topic-attributes":
        arn = options.get("--topic-arn")
        topics = SCENARIO.get("topics") or {}
        name = arn.rsplit(":", 1)[-1] if isinstance(arn, str) else None
        if arn != f"arn:{PARTITION}:sns:{region}:{ACCOUNT}:{name}" or name not in topics:
            not_found("GetTopicAttributes")
        attributes = {"TopicArn": arn, "Owner": ACCOUNT, "SubscriptionsConfirmed": "1",
                      "DisplayName": "", "EffectiveDeliveryPolicy": "{}"}
        attributes.update(topics[name])
        return {"Attributes": attributes}
    if operation == "simulate-principal-policy":
        source = options.get("--policy-source-arn")
        role = source.rsplit("/", 1)[-1] if isinstance(source, str) else None
        if role not in (SCENARIO.get("roles") or []) or f":{ACCOUNT}:" not in str(source):
            die(f"\nAn error occurred (NoSuchEntity) when calling the SimulatePrincipalPolicy operation: The role "
                f"with name {role} cannot be found. {SENTINEL}\n", 254)
        resources = as_list(options.get("--resource-arns"))
        decisions = SCENARIO.get("decisions") or {}
        results = []
        for action in as_list(options.get("--action-names")):
            decision = decisions.get(action, "allowed")
            results.append({"EvalActionName": action, "EvalResourceName": resources[0] if resources else "*",
                            "EvalDecision": decision, "MatchedStatements": [], "MissingContextValues": [],
                            "OrganizationsDecisionDetail": {"AllowedByOrganizations": True},
                            "ResourceSpecificResults": [{"EvalResourceName": resources[0] if resources else "*",
                                                         "EvalResourceDecision": decision,
                                                         "MatchedStatements": [], "MissingContextValues": []}]})
        return {"EvaluationResults": results, "IsTruncated": False}
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
    mode = failure(service, operation)
    if mode:
        simulate_failure(mode, service, operation, region, profile)
    print(json.dumps(answer(service, operation, options, region), indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
