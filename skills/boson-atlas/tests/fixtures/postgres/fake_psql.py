#!/usr/bin/env python3
"""psql falso da SPEC-0099 (adaptador postgres): aceita só a chamada da seção 6, responde com um cenário em JSON
como um servidor PostgreSQL responderia às consultas fixas do adaptador, e registra cada argv e as variáveis PG*.
Só biblioteca padrão; nenhum banco, nenhuma rede, nenhum ~/.pgpass, nenhum ~/.psqlrc.

Os testes copiam este arquivo como `psql` para uma pasta temporária (no PATH), com o cabeçalho trocado pelo Python
dos testes. O cenário fica ao lado da cópia, em `fake-psql.json` (o núcleo do probe só passa ao adaptador uma base
fixa de variáveis, então o dublê não depende do ambiente):
    {"record": "<arquivo .jsonl>",
     "ro": "on" | "off",                                    "off" = um pooler que descartou o PGOPTIONS
     "ro_off_for": ["detect" | "read" | "list"],            "ro" off só nessas consultas
     "histories": [{"nspname", "relname", "columns": [...], "rows": [{<coluna>: <valor>}, ...]}],
                   linhas do histórico da mais antiga para a mais recente, só com as colunas lidas pela seção 6
     "tables": [{"nspname", "relname", "relkind", "relispartition", "reltuples"}],   o que pg_class tem
     "fail": [{"mode": "<modo>", "query": "detect" | "read" | "list" (opcional)}]}

Forma única aceita (qualquer outra: registra, escreve no stderr e sai com 2):
    psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <porta> -U <usuário> -d <banco> -c <consulta>

Como o dublê reconhece a consulta (os marcadores fixos de cada entrada de QUERIES):
    - cita pg_attribute                         -> detect_migrations
    - cita relkind ou reltuples (sem pg_attribute) -> list_tables
    - cita exatamente um "<schema>"."<tabela>" de `histories` -> read_<formato> daquela tabela
    - nada disso                                -> sai com 2 ("consulta fora do dublê")

Resposta (stdout, exit 0): uma linha com um JSON {"ro": "on"|"off", "rows": [...]}:
    detect_migrations -> rows = [{"nspname", "relname", "columns": [<attname>, ...]}] das tabelas de `histories` cujo
                         nome aparece na consulta como literal ('<nome>'); vale para os nomes conhecidos e para o de
                         attrs.migrations_table. Pelo catálogo, a tabela aparece mesmo sem GRANT.
    read_<formato>    -> rows = as linhas daquela tabela, só com as colunas do formato (o dublê não interpreta o
                         SELECT), as mais recentes primeiro quando a consulta tem ORDER BY ... DESC.
    list_tables       -> rows = [{"nspname", "relname", "reltuples"}]; o dublê aplica os filtros que a consulta
                         cita: relkind (só 'r' e 'p'), relispartition (sem partições filhas), schemas do sistema
                         (pg_catalog, information_schema, pg_toast*, pg_temp*) quando a consulta os exclui.
    Em todas: ORDER BY ordena (detect e list por (schema, tabela)); LIMIT <n> corta; "ro" vem "off" quando o
    cenário pede ou quando o PGOPTIONS não tem default_transaction_read_only=on (o servidor não ficou só leitura).

- `record`: cada chamada vira uma linha JSON {"argv": [...], "env": {<PG*>: <valor>}, "query": <tipo>|null,
  "allowed": true|false}.
- Modos de `fail` (exit 2, texto parecido com o do psql real, com o host, o usuário, o banco e a palavra
  "sentinela-0099", para provar que o adaptador não os repete): auth, no-password, hba, connect, refused,
  permission, timeout, other; invalid-json (exit 0 com stdout que não é JSON).
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "fake-psql.json").read_text(encoding="utf-8"))
PREFIX = ["-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
IDENT_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*"([A-Za-z_][A-Za-z0-9_]*)"')
LIMIT_RE = re.compile(r"(?i)\blimit\s+(\d+)")
SYSTEM = ("pg_catalog", "information_schema")


def record(argv, query, allowed):
    path = SCENARIO.get("record")
    if path:
        env = {k: v for k, v in os.environ.items() if k.startswith("PG")}
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "env": env, "query": query, "allowed": allowed}) + "\n")


def die(text, code=2):
    sys.stderr.write(text)
    sys.exit(code)


def parse(argv):
    """(host, porta, usuário, banco, consulta) da forma única, ou None."""
    if len(argv) != 17 or argv[:7] != PREFIX:
        return None
    if [argv[7], argv[9], argv[11], argv[13], argv[15]] != ["-h", "-p", "-U", "-d", "-c"]:
        return None
    return argv[8], argv[10], argv[12], argv[14], argv[16]


def histories():
    return SCENARIO.get("histories") or []


def kind_of(query):
    low = query.lower()
    if "pg_attribute" in low:
        return "detect", None
    if "relkind" in low or "reltuples" in low:
        return "list", None
    known = {(h["nspname"], h["relname"]): h for h in histories()}
    found = {pair for pair in IDENT_RE.findall(query) if pair in known}
    if len(found) == 1:
        return "read", known[found.pop()]
    return None, None


def failure(kind):
    for rule in SCENARIO.get("fail") or []:
        if rule.get("query") in (None, kind):
            return rule["mode"]
    return ""


def simulate(mode, host, port, user, db, table):
    where = f'connection to server at "{host}" (10.0.0.5), port {port} failed'
    if mode == "auth":
        die(f'psql: error: {where}: FATAL:  password authentication failed for user "{user}" sentinela-0099\n')
    if mode == "no-password":
        die(f"psql: error: {where}: fe_sendauth: no password supplied (user {user}, db {db}) sentinela-0099\n")
    if mode == "hba":
        die(f'psql: error: {where}: FATAL:  no pg_hba.conf entry for host "10.0.0.9", user "{user}", database '
            f'"{db}", no encryption sentinela-0099\n')
    if mode == "connect":
        die(f'psql: error: could not translate host name "{host}" to address: nodename nor servname provided, or '
            "not known sentinela-0099\n")
    if mode == "refused":
        die(f"psql: error: {where}: Connection refused\n\tIs the server running on that host and accepting TCP/IP "
            "connections? sentinela-0099\n")
    if mode == "permission":
        die(f"ERROR:  permission denied for table {table} (user {user}, db {db}) sentinela-0099\n")
    if mode == "timeout":
        die(f"ERROR:  canceling statement due to statement timeout (host {host}, db {db}) sentinela-0099\n")
    if mode == "invalid-json":
        sys.stdout.write(f"not json at all {host} {user} {db} sentinela-0099\n")
        sys.exit(0)
    die(f"psql: error: something odd happened for {user}@{host}:{port}/{db} sentinela-0099\n")


def limited(query, rows):
    match = LIMIT_RE.search(query)
    return rows[: int(match.group(1))] if match else rows


def ordered(query, rows, key=None):
    low = query.lower()
    if "order by" not in low:
        return list(rows)
    if key is not None:
        return sorted(rows, key=key)
    return list(reversed(rows)) if re.search(r"\bdesc\b", low) else list(rows)


def system_schema(name):
    return name in SYSTEM or name.startswith(("pg_toast", "pg_temp"))


def answer(kind, query, history):
    low = query.lower()
    if kind == "detect":
        rows = [{"nspname": h["nspname"], "relname": h["relname"], "columns": list(h["columns"])}
                for h in histories() if f"'{h['relname']}'" in query and not system_schema(h["nspname"])]
        rows = ordered(query, rows, key=lambda r: (r["nspname"], r["relname"]))
        return limited(query, rows)
    if kind == "read":
        return limited(query, ordered(query, [dict(r) for r in history["rows"]]))
    rows = list(SCENARIO.get("tables") or [])
    if "relkind" in low:
        rows = [r for r in rows if r.get("relkind") in ("r", "p")]
    if "relispartition" in low:
        rows = [r for r in rows if not r.get("relispartition")]
    system = ("information_schema", "pg_catalog'", "'pg_%", "'pg\\_%", "^pg_")
    if any(marker in low for marker in system):
        rows = [r for r in rows if not system_schema(r["nspname"])]
    rows = ordered(query, rows, key=lambda r: (r["nspname"], r["relname"]))
    rows = [{"nspname": r["nspname"], "relname": r["relname"], "reltuples": r["reltuples"]} for r in rows]
    return limited(query, rows)


def read_only(kind):
    options = os.environ.get("PGOPTIONS", "")
    if "default_transaction_read_only=on" not in options.replace(" = ", "="):
        return "off"
    if kind in (SCENARIO.get("ro_off_for") or []):
        return "off"
    return SCENARIO.get("ro", "on")


def main(argv):
    parsed = parse(argv)
    if parsed is None:
        record(argv, None, False)
        die("psql: chamada fora da forma do contrato (dublê da SPEC-0099)\n")
    host, port, user, db, query = parsed
    kind, history = kind_of(query)
    record(argv, kind, kind is not None)
    if kind is None:
        die("psql: consulta fora do dublê (SPEC-0099)\n")
    mode = failure(kind)
    if mode:
        table = f"{history['nspname']}.{history['relname']}" if history else "pg_class"
        simulate(mode, host, port, user, db, table)
    print(json.dumps({"ro": read_only(kind), "rows": answer(kind, query, history)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
