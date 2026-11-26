"""Adaptador falso de mensageria probe@2 (SPEC-0104:IT-01): declara messaging (verbo queue, alvo queue) com
access: ["cloud"] e responde um item fixo, sem AWS CLI nem rede.

Uso: python3 fake_messaging.py --record <arquivo> [--adapter <id>]
O núcleo acrescenta --describe para pedir a descrição. Cada execução (sem --describe) acrescenta ao <arquivo> uma
linha JSON {"input": <JSON recebido no stdin>}.
"""
import json
import sys


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    adapter = option(argv, "--adapter", "fakemsg")
    if "--describe" in argv:
        print(json.dumps({"contract": "probe@2", "adapter": adapter, "capabilities": {
            "messaging": {"verbs": ["queue"], "targets": ["queue"], "access": ["cloud"]}}}))
        return 0
    data = json.loads(sys.stdin.read() or "{}")
    with open(option(argv, "--record"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"input": data}) + "\n")
    print(json.dumps({"contract": "probe@2", "adapter": adapter, "capability": data.get("capability"),
                      "verb": data.get("verb"), "status": "ok", "items": [{"name": "orders", "depth": 0}],
                      "truncated": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
