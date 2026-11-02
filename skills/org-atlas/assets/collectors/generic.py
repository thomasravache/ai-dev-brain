"""Coletor generic da org-atlas (SPEC-0034): converte um arquivo de fatos (JSON) na saída org-atlas/collector@1.

Uso: python3 generic.py --facts ARQUIVO --category C [--source NOME]

Esqueleto (G1): só a interface; a lógica chega no G2.
"""
import argparse
import sys

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "generic"


def convert_facts(facts, category, source=COLLECTOR):
    """Fatos ({"entities": [...], "relations": [...]}) -> saída do contrato com collector "generic"."""
    raise NotImplementedError("SPEC-0034: convert_facts")


def build_parser():
    parser = argparse.ArgumentParser(prog="generic.py", description="Coletor generic da org-atlas")
    parser.add_argument("--facts", required=True, help="arquivo de fatos (JSON)")
    parser.add_argument("--category", required=True, help="categoria do contrato (code, delivery, ...)")
    parser.add_argument("--source", default=COLLECTOR, help="valor de source (padrão: generic)")
    return parser


def main(argv=None):
    build_parser().parse_args(argv)
    raise NotImplementedError("SPEC-0034: generic.main")


if __name__ == "__main__":
    sys.exit(main())
