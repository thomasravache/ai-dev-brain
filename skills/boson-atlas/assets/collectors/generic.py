#!/usr/bin/env python3
"""generic collector of the boson-atlas (SPEC-0034): turns a hand-written facts file (JSON) into the
org-atlas/collector@1 output (ADR-0011). Stdlib only, Python 3.9+. It is also the example of how to write a
collector of your own (references/collectors/generic.md).

Usage: python3 generic.py --facts FILE --category C [--source NAME]

FILE: {"entities": [{"kind", "id", "name", "attrs"}], "relations": [{"from", "to", "type"}]}. `name` defaults to
the id and `attrs` to {}; the contract itself is checked by `atlas.py scan`. Every fact gets `source` NAME
(default "generic"). Missing file, invalid JSON or a fact without a required field: exit 1 with the reason.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "generic"
ENTITY_REQUIRED = ("kind", "id")
RELATION_REQUIRED = ("from", "to", "type")


class FactsError(Exception):
    """A facts file that cannot become the contract output; the message is shown as is (exit 1)."""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _items(facts: dict, field: str) -> list:
    items = facts.get(field, [])
    if not isinstance(items, list):
        raise FactsError(f"{field} precisa ser uma lista")
    return items


def _require(item, where: str, fields) -> None:
    if not isinstance(item, dict):
        raise FactsError(f"{where}: precisa ser um objeto")
    missing = [f for f in fields if item.get(f) in (None, "")]
    if missing:
        raise FactsError(f"{where}: falta o campo {', '.join(missing)}")


def convert_facts(facts, category, source=COLLECTOR):
    """Facts ({"entities": [...], "relations": [...]}) -> the contract output with collector "generic".
    The given facts are not changed; a fact without a required field raises FactsError with its index."""
    if not isinstance(facts, dict):
        raise FactsError("precisa ser um objeto JSON com entities e relations")
    entities = []
    for i, entity in enumerate(_items(facts, "entities")):
        _require(entity, f"entities[{i}]", ENTITY_REQUIRED)
        item = dict(entity, source=source)
        item.setdefault("name", entity["id"])
        item.setdefault("attrs", {})
        entities.append(item)
    relations = []
    for i, relation in enumerate(_items(facts, "relations")):
        _require(relation, f"relations[{i}]", RELATION_REQUIRED)
        relations.append(dict(relation, source=source))
    return {"contract": CONTRACT, "collector": COLLECTOR, "category": category, "collected_at": utc_now(),
            "entities": entities, "relations": relations}


def read_facts(path: str):
    """The facts file parsed; missing file or invalid JSON = FactsError "<file>: <reason>" (path as given)."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise FactsError(f"{path}: arquivo não encontrado") from None
    except (OSError, UnicodeDecodeError) as e:
        raise FactsError(f"{path}: não consegui ler ({getattr(e, 'strerror', None) or e})") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise FactsError(f"{path}: JSON inválido ({e.msg}, linha {e.lineno}, coluna {e.colno})") from None


def build_parser():
    parser = argparse.ArgumentParser(prog="generic.py", description="Coletor generic da org-atlas")
    parser.add_argument("--facts", required=True, help="arquivo de fatos (JSON)")
    parser.add_argument("--category", required=True, help="categoria do contrato (code, delivery, ...)")
    parser.add_argument("--source", default=COLLECTOR, help="valor de source (padrão: generic)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        facts = read_facts(args.facts)
        try:
            data = convert_facts(facts, args.category, source=args.source)
        except FactsError as e:
            raise FactsError(f"{args.facts}: {e}") from None
    except FactsError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
