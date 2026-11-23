"""Adaptador falso probe@1 (SPEC-0088): descreve as capacidades e, ao rodar, devolve status "error" com uma
mensagem que traz um token e um e-mail (montados em tempo de execução, nunca literais) — o núcleo precisa
mascará-los e sair com 1.

Uso: python3 error.py --record <arquivo> [--adapter <id>] [--verbs <capacidade>=<verbo>,<verbo>]...
"""
import json
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
with open(record_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"mode": mode, "argv": argv, "input": data}) + "\n")
if mode == "describe":
    print(json.dumps({"contract": "probe@1", "adapter": adapter, "capabilities": caps}))
    sys.exit(0)
token = "ghp_" + "Qw8" * 12
email = "pessoa.falsa" + "@" + "example.com"
print(json.dumps({"contract": "probe@1", "adapter": adapter, "capability": data.get("capability"),
                  "verb": data.get("verb"), "status": "error", "items": [], "truncated": False,
                  "message": f"MENSAGEM-ERRO-0088 token={token} usuario {email}"}))
