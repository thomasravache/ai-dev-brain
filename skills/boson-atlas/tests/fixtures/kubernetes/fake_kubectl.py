#!/usr/bin/env python3
"""`kubectl` falso da SPEC-0089 (UT-01 a UT-05, IT-01, CT-01): responde só `get` e `logs` de leitura com as respostas
gravadas de um cluster fictício (nomes `acme`), registra cada chamada e recusa qualquer outra. Só biblioteca padrão;
nenhum cluster, nenhuma rede.

Os testes copiam este arquivo como `kubectl` para uma pasta temporária, que vai no início do PATH, com o cabeçalho
trocado pelo Python dos testes. O cenário fica ao lado da cópia, em `fake-kubectl.json` (o núcleo do probe só passa ao
adaptador uma base fixa de variáveis, então o dublê não depende do ambiente):
    {"record": "<arquivo .jsonl>", "fixtures": "<pasta com as respostas>" | ["<pasta>", ...], "fail": "" | "forbidden"
     | "nocontext" | "timeout", "pod_fail": {"<pod>": "forbidden" | "nocontext" | "timeout" | "notfound"},
     "now": "<AAAA-MM-DDTHH:MM:SS+00:00>"}

- `now` (SPEC-0094): o "agora" fixo do cenário, em UTC, usado em todos os placeholders e no corte do `--since`; sem a
  chave, cada chamada usa o relógio do próprio processo.

- `record`: cada chamada vira uma linha JSON {"argv": [...]} (também as recusadas).
- `fixtures`: uma pasta ou uma lista de pastas (vale o `<recurso>.json` da primeira que o tiver; Emenda v5: os testes
  de resposta malformada põem uma pasta com um arquivo trocado na frente de `cluster/`). Em cada uma, `<recurso>.json` (objeto List, como `kubectl get <recurso> -o json`; recurso sem arquivo = lista vazia)
  e `logs.json` ({"<Kind>/<workload>": ["[pod/<pod>/<container>] <horário> <texto>", ...]}; o dublê filtra pelo pod
  pedido).
  Nos textos, `{{now-N}}` vira o horário de N segundos atrás (`AAAA-MM-DDTHH:MM:SSZ`) e `{{nano-N}}` o mesmo com
  nanossegundos (o formato de `kubectl logs --timestamps`). `{{frac-N-F}}` é o horário de N segundos atrás com a
  fração `.F`, sem os zeros do fim, e sem fração quando F só tem zeros (`{{frac-60-120}}` -> `...:SS.12Z`,
  `{{frac-60-0}}` -> `...:SSZ`), como o RFC 3339 com nanossegundos que o `kubectl logs --timestamps` imprime
  (Emenda v5).
- `fail`: falha simulada com a mensagem da CLI real e exit 1:
    forbidden = RBAC nega ("Error from server (Forbidden): ..."); nocontext = `error: context "<c>" does not exist`
    (com o contexto recebido); timeout = "Unable to connect to the server: ... (Client.Timeout exceeded ...)".
- `pod_fail` (Emenda v5): a mesma falha só no `logs` daquele pod; `notfound` = o pod sumiu entre o `get pods` e o
  `logs` ("Error from server (NotFound): pods \"<pod>\" not found").
- Pod que ainda não rodou (Emenda v5): o `logs` de um pod de `pods.json` em Pending, ou com um contêiner esperando
  (`state.waiting`) sem nunca ter rodado (restartCount 0), falha como o kubectl de verdade, com exit 1:
  `Error from server (BadRequest): container "<c>" in pod "<pod>" is waiting to start: <motivo>`. Um contêiner em
  CrashLoopBackOff (restartCount > 0) devolve as linhas, como o de verdade (as da última execução).

Chamadas aceitas (qualquer outra: exit 2, "chamada fora da lista do dublê"):
    get <recurso> [<nome>] -o json        recurso ∈ deployments, statefulsets, daemonsets, rollouts, replicasets,
                                          pods, events (com nome inexistente: NotFound, exit 1)
    logs pod/<nome> --all-containers --timestamps --since=<s>s --tail=<n> --prefix   (só pod/, um pod por chamada:
                                          o `logs Deployment/x` de verdade lê um pod só — Emenda v3; pod sem
                                          linhas = saída vazia)
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
PLACEHOLDER = re.compile(r"\{\{(now|nano)-(\d+)\}\}|\{\{frac-(\d+)-(\d{1,9})\}\}")
PREFIX = re.compile(r"^\[pod/(?P<pod>[^/\]]+)/(?P<container>[^\]]+)\] (?P<ts>\S+) ")
# SPEC-0094: o "agora" do cenário (gravado uma vez por `install_kubectl`) vale para todas as chamadas, que são processos
# separados; sem a chave, o relógio de cada processo.
NOW = (datetime.fromisoformat(SCENARIO["now"]).astimezone(timezone.utc) if SCENARIO.get("now")
       else datetime.now(timezone.utc)).replace(microsecond=0)


def record(argv):
    with open(SCENARIO["record"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv}) + "\n")


def refuse(argv):
    print(f"kubectl falso: chamada fora da lista do dublê: {' '.join(argv)}", file=sys.stderr)
    return 2


def render(text):
    def when(match):
        if match.group(3):
            moment = NOW - timedelta(seconds=int(match.group(3)))
            fraction = match.group(4).rstrip("0")
            return moment.strftime("%Y-%m-%dT%H:%M:%S") + (f".{fraction}" if fraction else "") + "Z"
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


def failure(options, resource, fail=None):
    fail = (SCENARIO.get("fail") or "") if fail is None else fail
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
    if fail == "notfound":
        print(f'Error from server (NotFound): pods "{resource}" not found', file=sys.stderr)
        return 1
    return 0


def load(name, default):
    folders = SCENARIO["fixtures"]
    for folder in [folders] if isinstance(folders, str) else folders:
        path = Path(folder) / name
        if path.is_file():
            return json.loads(render(path.read_text(encoding="utf-8")))
    return default


def waiting_to_start(name):
    """(contêiner, motivo) quando o pod `name` de pods.json ainda não rodou (o `logs` real falha), senão None."""
    for pod in load("pods.json", {"items": []}).get("items", []):
        if pod["metadata"]["name"] != name:
            continue
        status = pod.get("status") or {}
        containers = [c["name"] for c in (pod.get("spec") or {}).get("containers", [])]
        for container in status.get("containerStatuses") or []:
            waiting = (container.get("state") or {}).get("waiting")
            if waiting is not None and not container.get("restartCount"):
                return container["name"], waiting.get("reason") or "ContainerCreating"
        if status.get("phase") == "Pending":
            return (containers[0] if containers else name), "ContainerCreating"
    return None


def moment_of(stamp):
    """Horário RFC 3339 (com ou sem fração) -> (datetime, fração em nanossegundos), para ordenar pelo tempo real."""
    match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$", stamp)
    moment = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return moment, int((match.group(2) or "0").ljust(9, "0"))


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
    since = re.match(r"^(\d+)s$", str(options.get("--since", "")))
    tail = re.match(r"^\d+$", str(options.get("--tail", "")))
    if kind != "pod" or not name or not since or not tail or not LOGS_FLAGS <= set(options):
        return refuse(argv)
    code = failure(options, "pods")
    if code:
        return code
    pod_fail = (SCENARIO.get("pod_fail") or {}).get(name)
    if pod_fail:
        return failure(options, name if pod_fail == "notfound" else "pods", pod_fail)
    waiting = waiting_to_start(name)
    if waiting:
        print(f'Error from server (BadRequest): container "{waiting[0]}" in pod "{name}" is waiting to start: '
              f'{waiting[1]}', file=sys.stderr)
        return 1
    lines = [line for rows in load("logs.json", {}).values() for line in rows
             if PREFIX.match(line).group("pod") == name]
    limit = NOW - timedelta(seconds=int(since.group(1)))
    streams = {}
    for line in lines:
        match = PREFIX.match(line)
        moment = moment_of(match.group("ts"))
        if moment[0] >= limit:
            streams.setdefault((match.group("pod"), match.group("container")), []).append((moment, line))
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
