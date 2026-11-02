"""Coletor github da org-atlas (SPEC-0034): repositórios, workflows, CODEOWNERS e sinais de PR pelo `gh`.

Uso: python3 github.py --org ORG [--repos a,b] [--pr-sample N] [--input PASTA]

Esqueleto (G1): só a interface; a lógica chega no G2.
"""
import argparse
import sys

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "github"
DEFAULT_PR_SAMPLE = 100


def count_title_patterns(titles):
    """Títulos de PR -> {"total", "pattern_counts": {conventional, ticket_key, other}, "sample": [<= 10]}."""
    raise NotImplementedError("SPEC-0034: count_title_patterns")


def count_branch_prefixes(branches):
    """Branches de PR -> {"total", "counts": {"feat/": n, ...}}."""
    raise NotImplementedError("SPEC-0034: count_branch_prefixes")


def map_repository(org, repo):
    """Um repositório da resposta de repos -> entidade repository:<org>/<nome>."""
    raise NotImplementedError("SPEC-0034: map_repository")


def map_workflows(org, repo_name, response):
    """Resposta de actions/workflows -> (entidades pipeline, relações builds)."""
    raise NotImplementedError("SPEC-0034: map_workflows")


def parse_codeowners(org, repo_name, text):
    """Texto do CODEOWNERS -> (entidades team, relações owns); usuários e e-mails são ignorados."""
    raise NotImplementedError("SPEC-0034: parse_codeowners")


def map_policy(full_name, repo_response, has_template):
    """GET repos/{org}/{repo} e presença de template -> (sinais merge-methods e pr-template, avisos)."""
    raise NotImplementedError("SPEC-0034: map_policy")


def build_parser():
    parser = argparse.ArgumentParser(prog="github.py", description="Coletor github da org-atlas")
    parser.add_argument("--org", required=True, help="organização no GitHub")
    parser.add_argument("--repos", default=None, help="só estes repositórios (a,b)")
    parser.add_argument("--pr-sample", type=int, default=DEFAULT_PR_SAMPLE, help="PRs lidos por repositório")
    parser.add_argument("--input", default=None, help="pasta com respostas gravadas em vez do gh")
    return parser


def main(argv=None):
    build_parser().parse_args(argv)
    raise NotImplementedError("SPEC-0034: github.main")


if __name__ == "__main__":
    sys.exit(main())
