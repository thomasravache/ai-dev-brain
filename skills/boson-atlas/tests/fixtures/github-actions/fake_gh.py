#!/usr/bin/env python3
"""`gh` falso da SPEC-0106 (UT-01 a UT-04, IT-01, IT-02, CT-01): responde só
`gh api -X GET repos/<dono>/<repo>/actions/runs -f head_sha=<sha> -f per_page=<n>` com execuções gravadas por
repositório e por estado, simula as falhas do `gh` real, registra cada chamada e sai com 97 em qualquer argv fora da
lista. Só biblioteca padrão; nenhuma rede, nenhum GitHub.

Os testes copiam este arquivo como `gh` para uma pasta do PATH, com o cabeçalho trocado pelo Python dos testes. O
cenário fica ao lado da cópia, em `fake-gh.json` (o núcleo do probe só passa ao adaptador uma base fixa de variáveis,
então o dublê não depende do ambiente para o cenário):
    {"record": "<arquivo .jsonl>",
     "fixtures": "<pasta>" | ["<pasta>", ...],   # vale <pasta>/<dono>/<repo>.json da primeira que o tiver
     "repos": {"<dono>/<repo>": {"total_count": n, "workflow_runs": [...]}},   # resposta em linha (vence a pasta)
     "fail": {"<dono>/<repo>" | "*": "<modo>"},
     "echo": "<texto>"}                          # opcional: vai para o stderr de toda falha (sentinela)
  repositório sem resposta em linha nem arquivo = 404.
  modos de falha (a mensagem e o exit do gh real; corpo JSON no stdout quando o gh real imprime um):
    401          {"message": "Bad credentials"} / "gh: Bad credentials (HTTP 401)", exit 1
    noauth       "To get started with GitHub CLI, please run:  gh auth login ...", exit 4
    403          {"message": "Resource not accessible by integration"} / "gh: ... (HTTP 403)", exit 1
    rate-limit   {"message": "API rate limit exceeded for ..."} / "gh: API rate limit exceeded ... (HTTP 403)", exit 1
    rate-limit-429  o mesmo com HTTP 429
    404          {"message": "Not Found"} / "gh: Not Found (HTTP 404)", exit 1
    timeout      'Get "https://api.github.com/...": dial tcp 192.0.2.1:443: i/o timeout', exit 1
    invalid-json stdout que não é JSON, exit 0
  O stderr de toda falha traz a sentinela SENTINEL-STDERR-0106, o `echo` do cenário e o GH_TOKEN recebido (se houver):
  o adaptador nunca pode repassá-los.

Registro: cada chamada vira uma linha JSON {"argv": [...], "gh_token": <GH_TOKEN recebido ou null>,
"env_names": [nomes das variáveis recebidas]} (também as recusadas).
A resposta de sucesso traz no máximo `per_page` execuções (as primeiras do arquivo) e o `total_count` do arquivo.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-gh.json").read_text(encoding="utf-8"))
SENTINEL = "SENTINEL-STDERR-0106"
PATH_RE = re.compile(r"^repos/([^/\s]+)/([^/\s]+)/actions/runs$")
FIELD_RE = re.compile(r"^(head_sha|per_page)=(.*)$")


def record(argv):
    with open(SCENARIO["record"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "gh_token": os.environ.get("GH_TOKEN"),
                                 "env_names": sorted(os.environ)}) + "\n")


def refuse(argv):
    print(f"gh falso: chamada fora da lista do dublê: {' '.join(argv)}", file=sys.stderr)
    return 97


def parse(argv):
    """(dono/repo, {campo: valor}) de um argv permitido; None para qualquer outro."""
    if not argv or argv[0] != "api":
        return None
    method, path, fields, i = None, None, {}, 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("-X", "--method"):
            if i + 1 >= len(argv):
                return None
            method = argv[i + 1]
            i += 2
            continue
        if arg in ("-f", "--raw-field"):
            if i + 1 >= len(argv):
                return None
            match = FIELD_RE.match(argv[i + 1])
            if not match or match.group(1) in fields:
                return None
            fields[match.group(1)] = match.group(2)
            i += 2
            continue
        if arg.startswith("-") or path is not None:
            return None
        path = arg
        i += 1
    match = PATH_RE.match(path or "")
    if method != "GET" or not match or set(fields) != {"head_sha", "per_page"}:
        return None
    if not re.match(r"^[0-9a-f]{40}$", fields["head_sha"]) or not re.match(r"^\d{1,3}$", fields["per_page"]):
        return None
    return f"{match.group(1)}/{match.group(2)}", fields


def stderr_tail():
    parts = [SENTINEL, SCENARIO.get("echo") or "", os.environ.get("GH_TOKEN") or ""]
    return " ".join(p for p in parts if p)


def fail(mode, repository, fields):
    tail = stderr_tail()
    url = f"https://api.github.com/repos/{repository}/actions/runs?head_sha={quote(fields['head_sha'])}"
    if mode == "invalid-json":
        print("{\"total_count\": 1, \"workflow_runs\": [")
        return 0
    if mode == "noauth":
        print("To get started with GitHub CLI, please run:  gh auth login\nAlternatively, populate the GH_TOKEN "
              f"environment variable with a GitHub API authentication token. {tail}", file=sys.stderr)
        return 4
    if mode == "timeout":
        print(f'Get "{url}": dial tcp 192.0.2.1:443: i/o timeout {tail}', file=sys.stderr)
        return 1
    bodies = {"401": ("Bad credentials", 401), "403": ("Resource not accessible by integration", 403),
              "rate-limit": (("API rate limit exceeded for 192.0.2.10. (But here's the good news: Authenticated "
                              "requests get a higher rate limit.)"), 403),
              "rate-limit-429": ("API rate limit exceeded for 192.0.2.10.", 429),
              "404": ("Not Found", 404)}
    message, code = bodies[mode]
    print(json.dumps({"message": message, "documentation_url": "https://docs.github.com/rest",
                      "status": str(code)}))
    print(f"gh: {message} (HTTP {code}) {tail}", file=sys.stderr)
    return 1


def answer(repository):
    inline = SCENARIO.get("repos") or {}
    if repository in inline:
        return inline[repository]
    folders = SCENARIO.get("fixtures") or []
    owner, name = repository.split("/", 1)
    for folder in [folders] if isinstance(folders, str) else folders:
        path = Path(folder) / owner / f"{name}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def main(argv):
    record(argv)
    parsed = parse(argv)
    if parsed is None:
        return refuse(argv)
    repository, fields = parsed
    failures = SCENARIO.get("fail") or {}
    mode = failures.get(repository) or failures.get("*")
    if mode:
        return fail(mode, repository, fields)
    data = answer(repository)
    if data is None:
        return fail("404", repository, fields)
    runs = list(data.get("workflow_runs") or [])
    per_page = int(fields["per_page"])
    out = {"total_count": data.get("total_count", len(runs)), "workflow_runs": runs[:per_page]}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
