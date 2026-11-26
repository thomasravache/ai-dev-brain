#!/usr/bin/env python3
"""`kubectl` falso da SPEC-0106 (UT-05 a UT-07, IT-01, IT-02): responde `get applications.argoproj.io <nome>` com as
Applications gravadas por estado, simula as falhas do kubectl real e repassa as leituras de runtime (`get deployments`,
`replicasets`, `pods`, `events` e `logs pod/...`) ao kubectl falso da SPEC-0089 (fixtures/kubernetes/fake_kubectl.py),
com as respostas do mesmo estado. Registra cada argv e recusa (exit 2) qualquer outra chamada. Só biblioteca padrão;
nenhum cluster, nenhuma rede.

Os testes copiam este arquivo como `kubectl` para uma pasta do PATH, com o cabeçalho trocado pelo Python dos testes. O
cenário fica ao lado da cópia, em `fake-kubectl.json`:
    {"record": "<arquivo .jsonl>",
     "fixtures": "<pasta>" | ["<pasta>", ...],   # vale <pasta>/applications.json (objeto List) da primeira que o tiver
     "fail": "" | "forbidden" | "nocontext" | "timeout" | "nocrd" | "fail" | "invalid-json",
     "echo": "<texto>",                           # opcional: vai para o stderr de toda falha (sentinela)
     "runtime": "<caminho da cópia do kubectl falso da SPEC-0089>"}   # opcional: sem ele, runtime é recusado
  Estados de fixtures/delivery-track/states/: antes (CI sem execução, Application Synced/Healthy com a imagem antiga,
  pods antigos), ci (CI em andamento), gitops (CI ok, Application OutOfSync com a imagem do commit, pods antigos),
  pronto (Application Synced/Healthy e pods prontos com a imagem do commit); falha/gh traz só a CI com failure.

Chamada de Application aceita: get applications.argoproj.io <nome> -o json, com --context, -n/--namespace e
--request-timeout (com espaço ou "="). A Application é procurada pelo nome e pelo namespace pedido (padrão "default");
sem ela: `Error from server (NotFound): applications.argoproj.io "<nome>" not found`, exit 1. -A, -l, --raw,
--kubeconfig, sem nome ou com outro tipo: recusado.
Falhas (`fail`, só nas chamadas de Application; exit 1 e a mensagem do kubectl real, com o contexto recebido e a
sentinela SENTINEL-STDERR-0106 no stderr):
    forbidden  Error from server (Forbidden): applications.argoproj.io "<nome>" is forbidden: ...
    nocontext  error: context "<contexto>" does not exist
    timeout    Unable to connect to the server: ... (Client.Timeout exceeded while awaiting headers)
    nocrd      error: the server doesn't have a resource type "applications"
    fail       error: unexpected failure ...
    invalid-json  stdout que não é JSON, exit 0
Registro: cada chamada vira uma linha JSON {"argv": [...]} (também as recusadas e as repassadas).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-kubectl.json").read_text(encoding="utf-8"))
SENTINEL = "SENTINEL-STDERR-0106"
APP_TYPE = "applications.argoproj.io"
VALUE_OPTIONS = {"--context", "-n", "--namespace", "--request-timeout", "-o", "--output"}
RUNTIME = {"deployments", "statefulsets", "daemonsets", "rollouts", "replicasets", "pods", "events"}


def record(argv):
    with open(SCENARIO["record"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv}) + "\n")


def refuse(argv):
    print(f"kubectl falso: chamada fora da lista do dublê: {' '.join(argv)}", file=sys.stderr)
    return 2


def parse(argv):
    """(palavras, {opção: valor}) ou None com uma opção desconhecida."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if name in VALUE_OPTIONS:
            if not eq:
                if i + 1 >= len(argv):
                    return None
                value = argv[i + 1]
                i += 1
            options["-n" if name == "--namespace" else "-o" if name == "--output" else name] = value
        elif arg.startswith("-"):
            return None
        else:
            words.append(arg)
        i += 1
    return words, options


def applications():
    folders = SCENARIO.get("fixtures") or []
    for folder in [folders] if isinstance(folders, str) else folders:
        path = Path(folder) / "applications.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")).get("items", [])
    return []


def failure(mode, name, options):
    tail = " ".join(p for p in (SENTINEL, SCENARIO.get("echo") or "") if p)
    context = options.get("--context", "")
    if mode == "invalid-json":
        print("{\"apiVersion\": \"argoproj.io/v1alpha1\", \"kind\": ")
        return 0
    messages = {
        "forbidden": f'Error from server (Forbidden): {APP_TYPE} "{name}" is forbidden: User '
                     f'"system:serviceaccount:acme:reader" cannot get resource "applications" in API group '
                     f'"argoproj.io" in the namespace "{options.get("-n", "default")}" ({context}) {tail}',
        "nocontext": f'error: context "{context}" does not exist {tail}',
        "timeout": "Unable to connect to the server: context deadline exceeded (Client.Timeout exceeded while "
                   f"awaiting headers) {tail}",
        "nocrd": f'error: the server doesn\'t have a resource type "applications" {tail}',
        "fail": f"error: unexpected failure talking to {context} {tail}",
    }
    print(messages[mode], file=sys.stderr)
    return 1


def get_application(argv, words, options):
    if len(words) != 3 or options.get("-o") != "json":
        return refuse(argv)
    name = words[2]
    mode = SCENARIO.get("fail") or ""
    if mode:
        return failure(mode, name, options)
    namespace = options.get("-n", "default")
    for app in applications():
        meta = app.get("metadata") or {}
        if meta.get("name") == name and meta.get("namespace", "default") == namespace:
            print(json.dumps(app, indent=2, ensure_ascii=False))
            return 0
    print(f'Error from server (NotFound): {APP_TYPE} "{name}" not found', file=sys.stderr)
    return 1


def main(argv):
    record(argv)
    parsed = parse(argv)
    if parsed is None:
        if argv[:1] == ["logs"] and SCENARIO.get("runtime"):
            os.execv(sys.executable, [sys.executable, SCENARIO["runtime"], *argv])
        return refuse(argv)
    words, options = parsed
    if words[:2] == ["get", APP_TYPE]:
        return get_application(argv, words, options)
    runtime = SCENARIO.get("runtime")
    if runtime and (words[:1] == ["logs"] or (words[:1] == ["get"] and len(words) >= 2 and words[1] in RUNTIME)):
        os.execv(sys.executable, [sys.executable, runtime, *argv])
    return refuse(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
