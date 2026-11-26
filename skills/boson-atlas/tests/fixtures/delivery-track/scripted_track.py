"""Adaptador falso com roteiro para as regras de etapa do `verify track` (SPEC-0106: UT-08 a UT-14, CT-02): a descrição
vem de um arquivo JSON (probe@1 ou probe@2, o teste escolhe) e a resposta de cada verbo, por deployment do alvo, de um
arquivo de cenário. Nenhum gh, kubectl, argocd nem rede. Junta o roteiro por deployment de fake-probes/scripted.py com
a descrição em arquivo de fake-probes/probe2.py (uma capacidade com `inputs: ["change"]` precisa do probe@2).

Uso: python3 scripted_track.py --record <arquivo> --describe-file <descrição.json> --scenario <cenário.json>
                               [--adapter <id>]
O núcleo acrescenta --describe para pedir a descrição (impressa como está, com "adapter" = --adapter quando falta).
Cada chamada acrescenta ao <arquivo> uma linha JSON {"mode": "describe" | "run", "adapter": <id>, "argv": [...],
"input": <JSON do stdin>, "env": {<nome>: <valor>}}.

Cenário (lido a cada execução): {"<verbo>": {"<deployment>" | "*": <resposta>}}; vale a entrada de
target.deployment e, sem ela, a de "*"; sem nenhuma = itens vazios.
    <resposta>:
        {"items": [...], "truncated": false, "message": "..."}  status "ok" com esses itens
        {"error": "<mensagem>"}                                   status "error", itens vazios, a mensagem (exit 0)
        {"exit": <n>, "stderr": "<texto>"}                         escreve no stderr e sai com n
Nos textos dos itens e da mensagem, "{{env:<NOME>}}" vira o valor da variável recebida e "{{target:<chave>}}" o valor
de target.<chave> recebido: o dublê ecoa a credencial e o contexto para os testes da máscara (UT-14).
"""
import json
import os
import re
import sys

PLACEHOLDER = re.compile(r"\{\{(env|target):([A-Za-z0-9_]+)\}\}")


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def record(argv, adapter, mode, data=None):
    with open(option(argv, "--record"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"mode": mode, "adapter": adapter, "argv": argv, "input": data,
                                 "env": dict(os.environ)}) + "\n")


def fill(value, target):
    if isinstance(value, str):
        def sub(match):
            if match.group(1) == "env":
                return os.environ.get(match.group(2), "")
            found = target.get(match.group(2), "")
            return found if isinstance(found, str) else json.dumps(found)
        return PLACEHOLDER.sub(sub, value)
    if isinstance(value, list):
        return [fill(v, target) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, target) for k, v in value.items()}
    return value


def main(argv):
    adapter = option(argv, "--adapter", "fake-track")
    with open(option(argv, "--describe-file"), encoding="utf-8") as handle:
        described = json.load(handle)
    described.setdefault("adapter", adapter)
    if "--describe" in argv:
        record(argv, adapter, "describe")
        print(json.dumps(described))
        return 0
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {"raw": raw}
    record(argv, adapter, "run", data)
    with open(option(argv, "--scenario"), encoding="utf-8") as handle:
        scenario = json.load(handle)
    target = data.get("target") or {}
    by_deployment = scenario.get(data.get("verb")) or {}
    answer = by_deployment.get(target.get("deployment")) or by_deployment.get("*") or {}
    if "exit" in answer:
        sys.stderr.write(answer.get("stderr", "falha do adaptador falso") + "\n")
        return int(answer["exit"])
    out = {"contract": described.get("contract"), "adapter": adapter, "capability": data.get("capability"),
           "verb": data.get("verb"), "status": "ok", "items": fill(list(answer.get("items", [])), target),
           "truncated": bool(answer.get("truncated", False))}
    if answer.get("message"):
        out["message"] = fill(answer["message"], target)
    if "error" in answer:
        out.update(status="error", items=[], truncated=False, message=fill(answer["error"], target))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
