#!/usr/bin/env python3
"""`kubectl` falso da SPEC-0089 (UT-01 a UT-05, IT-01, CT-01): responde só `get` e `logs` de leitura com as respostas
gravadas de um cluster fictício (nomes `acme`), registra cada chamada e recusa qualquer outra. Só biblioteca padrão;
nenhum cluster, nenhuma rede.

Os testes copiam este arquivo como `kubectl` para uma pasta temporária, que vai no início do PATH, com o cabeçalho
trocado pelo Python dos testes. O cenário fica ao lado da cópia, em `fake-kubectl.json` (o núcleo do probe só passa ao
adaptador uma base fixa de variáveis, então o dublê não depende do ambiente):
    {"record": "<arquivo .jsonl>", "fixtures": "<pasta com as respostas>", "fail": "" | "forbidden" | "nocontext"
     | "timeout"}

- `record`: cada chamada vira uma linha JSON {"argv": [...]} (também as recusadas).
- `fixtures`: `<recurso>.json` (objeto List, como `kubectl get <recurso> -o json`; recurso sem arquivo = lista vazia)
  e `logs.json` ({"<kind>/<nome>": ["[pod/<pod>/<container>] <horário> <texto>", ...]}).
  Nos textos, `{{now-N}}` vira o horário de N segundos atrás (`AAAA-MM-DDTHH:MM:SSZ`) e `{{nano-N}}` o mesmo com
  nanossegundos (o formato de `kubectl logs --timestamps`).
- `fail`: falha simulada com a mensagem da CLI real e exit 1:
    forbidden = RBAC nega ("Error from server (Forbidden): ..."); nocontext = `error: context "<c>" does not exist`
    (com o contexto recebido); timeout = "Unable to connect to the server: ... (Client.Timeout exceeded ...)".

Chamadas aceitas (qualquer outra: exit 2, "chamada fora da lista do dublê"):
    get <recurso> [<nome>] -o json        recurso ∈ deployments, statefulsets, daemonsets, rollouts, replicasets,
                                          pods, events (com nome inexistente: NotFound, exit 1)
    logs <kind>/<nome> --all-containers --timestamps --since=<s>s --tail=<n> --prefix
    opções globais aceitas: --context, -n/--namespace, --request-timeout (com espaço ou `=`).
`--since` descarta as linhas mais velhas que a janela; `--tail` guarda as últimas n de cada (pod, container).
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-kubectl.json").read_text(encoding="utf-8"))
RESOURCES = ("deployments", "statefulsets", "daemonsets", "rollouts", "replicasets", "pods", "events")
GLOBAL_VALUE = {"--context", "-n", "--namespace", "--request-timeout"}
GET_VALUE = GLOBAL_VALUE | {"-o", "--output"}
LOGS_VALUE = GLOBAL_VALUE | {"--since", "--tail"}
LOGS_FLAGS = {"--all-containers", "--timestamps", "--prefix"}
PLACEHOLDER = re.compile(r"\{\{(now|nano)-(\d+)\}\}")
PREFIX = re.compile(r"^\[pod/(?P<pod>[^/\]]+)/(?P<container>[^\]]+)\] (?P<ts>\S+) ")
KINDS = {"deployment": "deployment", "deployments": "deployment", "deploy": "deployment",
         "statefulset": "statefulset", "statefulsets": "statefulset", "sts": "statefulset",
         "daemonset": "daemonset", "daemonsets": "daemonset", "ds": "daemonset",
         "rollout": "rollout", "rollouts": "rollout", "replicaset": "replicaset", "replicasets": "replicaset",
         "rs": "replicaset", "pod": "pod", "pods": "pod", "po": "pod"}
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def record(argv):
    with open(SCENARIO["record"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv}) + "\n")


def refuse(argv):
    print(f"kubectl falso: chamada fora da lista do dublê: {' '.join(argv)}", file=sys.stderr)
    return 2


def render(text):
    def when(match):
        moment = NOW - timedelta(seconds=int(match.group(2)))
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%S")
        return stamp + (".000000000Z" if match.group(1) == "nano" else "Z")
    return PLACEHOLDER.sub(when, text)


def parse(argv, value_options, flags):
    """(palavras posicionais, {opção: valor}); None quando há uma opção desconhecida."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if name in value_options:
            if not eq:
                if i + 1 >= len(argv):
                    return None
                value = argv[i + 1]
                i += 1
            options[name] = value
        elif name in flags and (not eq or value in ("true", "")):
            options[name] = True
        elif arg.startswith("-"):
            return None
        else:
            words.append(arg)
        i += 1
    return words, options


def failure(options, resource):
    fail = SCENARIO.get("fail") or ""
    if fail == "forbidden":
        print(f'Error from server (Forbidden): {resource} is forbidden: User "system:serviceaccount:acme:reader" '
              f'cannot list resource "{resource}" in API group "" in the namespace '
              f'"{options.get("-n") or options.get("--namespace") or "default"}"', file=sys.stderr)
        return 1
    if fail == "nocontext":
        print(f'error: context "{options.get("--context", "")}" does not exist', file=sys.stderr)
        return 1
    if fail == "timeout":
        print("Unable to connect to the server: context deadline exceeded (Client.Timeout exceeded while awaiting "
              "headers)", file=sys.stderr)
        return 1
    return 0


def load(name, default):
    path = Path(SCENARIO["fixtures"]) / name
    if not path.is_file():
        return default
    return json.loads(render(path.read_text(encoding="utf-8")))


def get(argv):
    parsed = parse(argv[1:], GET_VALUE, set())
    if parsed is None:
        return refuse(argv)
    words, options = parsed
    output = options.get("-o", options.get("--output"))
    if not words or words[0] not in RESOURCES or len(words) > 2 or output != "json":
        return refuse(argv)
    code = failure(options, words[0])
    if code:
        return code
    data = load(f"{words[0]}.json", {"apiVersion": "v1", "kind": "List", "items": [], "metadata": {}})
    if len(words) == 2:
        found = [item for item in data["items"] if item["metadata"]["name"] == words[1]]
        if not found:
            print(f'Error from server (NotFound): {words[0]} "{words[1]}" not found', file=sys.stderr)
            return 1
        data = found[0]
    print(json.dumps(data, indent=4))
    return 0


def logs(argv):
    parsed = parse(argv[1:], LOGS_VALUE, LOGS_FLAGS)
    if parsed is None:
        return refuse(argv)
    words, options = parsed
    if len(words) != 1 or "/" not in words[0]:
        return refuse(argv)
    kind, _, name = words[0].partition("/")
    kind = KINDS.get(kind.lower())
    since = re.match(r"^(\d+)s$", str(options.get("--since", "")))
    tail = re.match(r"^\d+$", str(options.get("--tail", "")))
    if kind is None or not name or not since or not tail or not LOGS_FLAGS <= set(options):
        return refuse(argv)
    code = failure(options, "pods")
    if code:
        return code
    table = {key.lower(): lines for key, lines in load("logs.json", {}).items()}
    if kind == "pod":
        lines = [line for rows in table.values() for line in rows if PREFIX.match(line).group("pod") == name]
    else:
        lines = table.get(f"{kind}/{name.lower()}")
        if lines is None:
            print(f'Error from server (NotFound): {kind}s.apps "{name}" not found', file=sys.stderr)
            return 1
    limit = NOW - timedelta(seconds=int(since.group(1)))
    streams = {}
    for line in lines:
        match = PREFIX.match(line)
        moment = datetime.strptime(match.group("ts")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if moment >= limit:
            streams.setdefault((match.group("pod"), match.group("container")), []).append((match.group("ts"), line))
    for key in streams:
        rows = sorted(streams[key])[-int(tail.group(0)):]
        for _, line in rows:
            print(line)
    return 0


def main(argv):
    record(argv)
    if argv[:1] == ["get"]:
        return get(argv)
    if argv[:1] == ["logs"]:
        return logs(argv)
    return refuse(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
