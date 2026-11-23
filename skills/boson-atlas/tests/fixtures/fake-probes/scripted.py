"""Adaptador falso probe@1 com roteiro (SPEC-0090): responde cada verbo com a resposta gravada num arquivo de cenário,
por deployment do alvo. Os testes reescrevem o cenário entre o `verify snapshot` e o `verify compare` (o estado
"antes" e o "depois"), sem nenhum kubectl e sem rede.

Uso: python3 scripted.py --record <arquivo> --scenario <cenário.json> [--adapter <id>]
                         [--verbs <capacidade>=<verbo>,<verbo>]...
O núcleo acrescenta --describe para pedir a descrição. Cada chamada acrescenta ao <arquivo> uma linha JSON
{"mode": "describe" | "run", "argv": [...], "input": <JSON do stdin>} (o registro de processos do dublê).

Cenário (lido a cada execução):
    {"<deployment>": {"<verbo>": <resposta>}, "*": {"<verbo>": <resposta>}}
    vale a entrada de target.deployment e, sem ela, a de "*"; verbo sem resposta = itens vazios.
    <resposta>:
        {"items": [...], "truncated": false}   status "ok" com esses itens
        {"error": "<mensagem>"}                 status "error", itens vazios, a mensagem (exit 0)
        {"exit": <n>, "stderr": "<texto>"}      o adaptador quebra: escreve no stderr e sai com n
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


def main(argv):
    adapter = option(argv, "--adapter", "fake")
    if "--describe" in argv:
        record(argv, "describe")
        print(json.dumps({"contract": "probe@1", "adapter": adapter, "capabilities": capabilities(argv)}))
        return 0
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {"raw": raw}
    record(argv, "run", data)
    with open(option(argv, "--scenario"), encoding="utf-8") as handle:
        scenario = json.load(handle)
    deployment = (data.get("target") or {}).get("deployment")
    answers = scenario.get(deployment) or scenario.get("*") or {}
    answer = answers.get(data.get("verb")) or {}
    if "exit" in answer:
        sys.stderr.write(answer.get("stderr", "falha do adaptador falso") + "\n")
        return int(answer["exit"])
    out = {"contract": "probe@1", "adapter": adapter, "capability": data.get("capability"), "verb": data.get("verb"),
           "status": "ok", "items": answer.get("items", []), "truncated": bool(answer.get("truncated", False))}
    if "error" in answer:
        out.update(status="error", items=[], truncated=False, message=answer["error"])
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
