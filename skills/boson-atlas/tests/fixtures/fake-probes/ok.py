"""Adaptador falso probe@1 (SPEC-0088): descreve as capacidades e responde status ok.

Uso: python3 ok.py --record <arquivo> [--adapter <id>] [--verbs <capacidade>=<verbo>,<verbo>]...
                   [--items <arquivo.json>] [--repeat N]
O núcleo acrescenta --describe para pedir a descrição. Cada chamada acrescenta ao <arquivo> uma linha JSON
{"mode": "describe" | "run", "argv": [...], "input": <JSON do stdin>} (o registro de processos do dublê).
Sem --items, devolve um item fixo; --repeat repete a lista de itens N vezes.
"""
import json
import sys


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def capabilities(argv):
    caps = {}
    for i, arg in enumerate(argv):
        if arg == "--verbs":
            cap, _, verbs = argv[i + 1].partition("=")
            caps[cap] = [v for v in verbs.split(",") if v]
    return caps or {"runtime": ["status", "events", "logs"]}


def record(argv, mode, data=None):
    with open(option(argv, "--record"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"mode": mode, "argv": argv, "input": data}) + "\n")


argv = sys.argv[1:]
adapter = option(argv, "--adapter", "fake")
if "--describe" in argv:
    record(argv, "describe")
    print(json.dumps({"contract": "probe@1", "adapter": adapter, "capabilities": capabilities(argv)}))
    sys.exit(0)
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except ValueError:
    data = {"raw": raw}
record(argv, "run", data)
items_file = option(argv, "--items")
if items_file:
    with open(items_file, encoding="utf-8") as handle:
        items = json.load(handle)
else:
    items = [{"kind": "Deployment", "name": "api", "ready": "1/1", "restarts": 0}]
items = items * int(option(argv, "--repeat", "1"))
print(json.dumps({"contract": "probe@1", "adapter": adapter, "capability": data.get("capability"),
                  "verb": data.get("verb"), "status": "ok", "items": items, "truncated": False,
                  "message": "ok"}))
