"""Adaptador falso probe@2 com roteiro por recurso (SPEC-0102): responde cada verbo com a resposta gravada num arquivo
de cenário, por `kind:id` do target.resource, sem nenhuma CLI de nuvem, psql, kubectl nem rede. Os testes reescrevem o
cenário entre o `verify snapshot` e o `verify compare` (o estado "antes" e o "depois").

Uso: python3 scripted_resources.py --record <arquivo> --scenario <cenário.json> [--describe-file <descrição.json>]
                                   [--adapter <id>]
O núcleo acrescenta --describe para pedir a descrição. Sem --describe-file, o adaptador declara as quatro capacidades
de recurso da regra 4a do ADR-0026 (DEFAULT_CAPABILITIES); com ele, o arquivo traz {"capabilities": {...}} (e, se
quiser, "contract"), lido a cada execução.
Cada chamada acrescenta ao <arquivo> uma linha JSON {"mode": "describe" | "run", "argv": [...], "input": <JSON do
stdin>} (o registro de processos do dublê).

Cenário (lido a cada execução):
    {"<kind:id>": {"<verbo>": <resposta>}, "*": {"<verbo>": <resposta>}}
    vale a entrada do target.resource (kind:id) e, sem ela, a de "*"; verbo sem resposta = itens vazios.
    <resposta>:
        {"items": [...], "truncated": false}   status "ok" com esses itens
        {"error": "<mensagem>"}                 status "error", itens vazios, a mensagem (exit 0)
        {"exit": <n>, "stderr": "<texto>"}      o adaptador quebra: escreve no stderr e sai com n
"""
import json
import sys

DEFAULT_CAPABILITIES = {
    "messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]},
    "database": {"verbs": ["migrations", "tables"], "targets": ["datastore"], "access": ["database"]},
    "signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"], "access": ["cloud"]},
    "permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"], "access": ["cloud"]},
}


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def record(argv, mode, data=None):
    with open(option(argv, "--record"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"mode": mode, "argv": argv, "input": data}) + "\n")


def described(argv):
    path = option(argv, "--describe-file")
    data = {}
    if path:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    return {"contract": data.get("contract", "probe@2"), "adapter": option(argv, "--adapter", "fake-res"),
            "capabilities": data.get("capabilities", DEFAULT_CAPABILITIES)}


def main(argv):
    describe = described(argv)
    if "--describe" in argv:
        record(argv, "describe")
        print(json.dumps(describe))
        return 0
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {"raw": raw}
    record(argv, "run", data)
    with open(option(argv, "--scenario"), encoding="utf-8") as handle:
        scenario = json.load(handle)
    resource = (data.get("target") or {}).get("resource") or {}
    key = f"{resource.get('kind')}:{resource.get('id')}"
    answers = scenario.get(key) or scenario.get("*") or {}
    answer = answers.get(data.get("verb")) or {}
    if "exit" in answer:
        sys.stderr.write(answer.get("stderr", "falha do adaptador falso") + "\n")
        return int(answer["exit"])
    out = {"contract": describe["contract"], "adapter": describe["adapter"], "capability": data.get("capability"),
           "verb": data.get("verb"), "status": "ok", "items": answer.get("items", []),
           "truncated": bool(answer.get("truncated", False))}
    if "error" in answer:
        out.update(status="error", items=[], truncated=False, message=answer["error"])
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
