"""Adaptador falso probe@1 (SPEC-0088): eco das credenciais por nome. Ao rodar, grava no registro e devolve como
itens só os NOMES das variáveis *_TOKEN que recebeu no ambiente (nunca os valores).

Uso: python3 env_names.py --record <arquivo> [--adapter <id>] [--verbs <capacidade>=<verbo>,<verbo>]...
"""
import json
import os
import sys

argv = sys.argv[1:]
record_path = argv[argv.index("--record") + 1]
adapter = argv[argv.index("--adapter") + 1] if "--adapter" in argv else "fake"
caps = {}
for i, arg in enumerate(argv):
    if arg == "--verbs":
        cap, _, verbs = argv[i + 1].partition("=")
        caps[cap] = [v for v in verbs.split(",") if v]
caps = caps or {"runtime": ["status", "events", "logs"]}
mode = "describe" if "--describe" in argv else "run"
data = None if mode == "describe" else json.loads(sys.stdin.read() or "{}")
names = sorted(name for name in os.environ if name.endswith("_TOKEN"))
with open(record_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"mode": mode, "argv": argv, "input": data, "env_names": names}) + "\n")
if mode == "describe":
    print(json.dumps({"contract": "probe@1", "adapter": adapter, "capabilities": caps}))
    sys.exit(0)
print(json.dumps({"contract": "probe@1", "adapter": adapter, "capability": data.get("capability"),
                  "verb": data.get("verb"), "status": "ok", "items": [{"name": n} for n in names],
                  "truncated": False, "message": "ok"}))
