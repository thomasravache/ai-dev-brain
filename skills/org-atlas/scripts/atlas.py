#!/usr/bin/env python3
"""Deterministic tooling for the org-atlas skill (stdlib only, Python 3.9+). Run with --help.

Scaffold (SPEC-0032): CLI skeleton and stubs only; the behavior comes with the Green phase.
Two configuration layers: the local one, per machine, in $ATLAS_CONFIG_HOME/config.yml (atlas path and credential
names) and the shared one, in <atlas>/atlas-config.yml (ADR-0010).
"""
from __future__ import annotations

import argparse
import sys


class AtlasError(Exception):
    """Error shown to the user without a traceback; `code` is the exit code."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def parse_yaml(text):
    raise NotImplementedError("parse_yaml (SPEC-0032)")


def dump_yaml(data):
    raise NotImplementedError("dump_yaml (SPEC-0032)")


def render_atlas_config(organization, mode):
    raise NotImplementedError("render_atlas_config (SPEC-0032)")


def validate_credentials(credentials):
    raise NotImplementedError("validate_credentials (SPEC-0032)")


def load_config(config_home=None):
    raise NotImplementedError("load_config (SPEC-0032)")


def run_collector(argv):
    raise NotImplementedError("run_collector (SPEC-0033)")


def cmd_init(args):
    raise NotImplementedError("cmd_init (SPEC-0032)")


def cmd_config(as_json):
    raise NotImplementedError("cmd_config (SPEC-0032)")


def cmd_doctor(as_json):
    raise NotImplementedError("cmd_doctor (SPEC-0032)")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="atlas.py", description="Ferramentas determinísticas do org-atlas.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="cria um atlas novo ou só liga esta máquina (--join)")
    p.add_argument("--atlas", required=True, help="pasta do atlas")
    p.add_argument("--org", help="nome da organização")
    p.add_argument("--mode", help="repo | local")
    p.add_argument("--force", action="store_true", help="substitui atlas-config.yml diferente (anterior em .bak)")
    p.add_argument("--join", action="store_true", help="atlas já configurado: grava só a configuração local")
    p = sub.add_parser("config", help="configuração efetiva e a origem de cada valor (local | atlas | padrão)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "config":
            return cmd_config(args.json)
        if args.command == "doctor":
            return cmd_doctor(args.json)
    except AtlasError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    return 2


if __name__ == "__main__":
    sys.exit(main())
