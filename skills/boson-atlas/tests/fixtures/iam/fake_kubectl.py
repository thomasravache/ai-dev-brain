#!/usr/bin/env python3
"""`kubectl` falso da SPEC-0101 (adaptador iam): responde só `get <recurso> <nome> -o json` de workloads e de
ServiceAccounts, com objetos de um cenário em JSON, registra cada argv e recusa qualquer outra chamada. Só biblioteca
padrão; nenhum cluster, nenhuma rede, nenhum ~/.kube.

Os testes copiam este arquivo como `kubectl` para uma pasta temporária (no PATH), com o cabeçalho trocado pelo Python
dos testes. O cenário fica ao lado da cópia, em `fake-kubectl.json`:
    {"record": "<arquivo .jsonl>",
     "objects": {"<recurso>/<nome>": {<objeto como `kubectl get -o json` devolve>}},
     "fail": "" | "forbidden" | "nocontext" | "timeout" | "invalid-json" | "fail",
     "fail_on": "<recurso>"?}        a falha só no get daquele recurso (ex.: serviceaccounts)

- `record`: cada chamada vira uma linha JSON {"argv": [...], "allowed": true|false}.
- Objeto ausente: `Error from server (NotFound): <recurso> "<nome>" not found`, exit 1.
- Falhas com o texto parecido com o da CLI real e o marcador SENTINEL-STDERR-0101 (com o contexto recebido), para
  provar que o adaptador não repete o stderr: forbidden (RBAC), nocontext (`error: context "<c>" does not exist`),
  timeout (Client.Timeout exceeded), invalid-json (exit 0 com JSON quebrado), fail (erro livre, exit 1).

Chamadas aceitas (qualquer outra: exit 2, "chamada fora da lista do dublê"):
    get <deployments|statefulsets|daemonsets|rollouts|serviceaccounts> <nome> -o json
    opções globais: --context, -n/--namespace, --request-timeout (com espaço ou `=`).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-kubectl.json").read_text(encoding="utf-8"))
RESOURCES = ("deployments", "statefulsets", "daemonsets", "rollouts", "serviceaccounts")
VALUE_OPTIONS = {"--context", "-n", "--namespace", "--request-timeout", "-o", "--output"}
SENTINEL = "SENTINEL-STDERR-0101"


def parse(argv):
    """(palavras, {opção: valor}) ou None quando há opção desconhecida."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("-"):
            name, eq, value = arg.partition("=")
            if name not in VALUE_OPTIONS:
                return None
            if not eq:
                i += 1
                if i >= len(argv):
                    return None
                value = argv[i]
            options[name] = value
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


def main(argv):
    parsed = parse(argv)
    words, options = parsed if parsed else ([], {})
    allowed = (parsed is not None and len(words) == 3 and words[0] == "get" and words[1] in RESOURCES
               and options.get("-o", options.get("--output")) == "json")
    record(argv, allowed)
    if not allowed:
        die(f"error: chamada fora da lista do dublê: {' '.join(argv)}\n", 2)
    _, resource, name = words
    context = options.get("--context", "")
    mode = SCENARIO.get("fail") or ""
    if mode and SCENARIO.get("fail_on") in (None, resource):
        if mode == "forbidden":
            die(f'Error from server (Forbidden): {resource} "{name}" is forbidden: User "system:serviceaccount:'
                f'{context}:reader" cannot get resource "{resource}" in API group "" ({SENTINEL})\n', 1)
        if mode == "nocontext":
            die(f'error: context "{context}" does not exist ({SENTINEL})\n', 1)
        if mode == "timeout":
            die(f"Unable to connect to the server: dial tcp 10.0.0.1:443: i/o timeout (Client.Timeout exceeded "
                f"while awaiting headers) {context} {SENTINEL}\n", 1)
        if mode == "invalid-json":
            sys.stdout.write('{"kind": "Deployment", "broken": \n')
            sys.exit(0)
        die(f"error: something odd happened for {context} ({SENTINEL})\n", 1)
    obj = (SCENARIO.get("objects") or {}).get(f"{resource}/{name}")
    if obj is None:
        die(f'Error from server (NotFound): {resource} "{name}" not found ({SENTINEL})\n', 1)
    print(json.dumps(obj, indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
