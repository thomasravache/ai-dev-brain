#!/usr/bin/env python3
"""Coletor argocd da org-atlas (SPEC-0035), categoria delivery: deployments, serviços, ambientes, clusters, a
origem de cada deployment e as referências de configuração, lidos das Applications do Argo CD.

Uso: python3 argocd.py --from argocd|kubectl [--env-label CHAVE] [--service-label CHAVE]
                       [--ref-suffixes _HOST,_URL,...] [--input ARQUIVO]

Esqueleto (G1): só a interface; a lógica chega no G2.
"""
import argparse
import sys

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "argocd"
CATEGORY = "delivery"
DEFAULT_ENV_LABEL = "env"
DEFAULT_SERVICE_LABEL = "app.kubernetes.io/part-of"
DEFAULT_REF_SUFFIXES = ("_HOST", "_URL", "_DSN", "_ADDR", "_QUEUE", "_TOPIC", "_BUCKET")


def host_of(value):
    """Valor de configuração -> só o host ou o nome do recurso (sem credencial, porta, caminho e query); None
    quando não sobra nada."""
    raise NotImplementedError("SPEC-0035: host_of")


def extract_config_refs(source, suffixes=DEFAULT_REF_SUFFIXES):
    """spec.source de uma Application -> lista ordenada e sem repetição de "CHAVE=host" (helm.parameters,
    helm.values, helm.valuesObject e plugin.env), só das chaves que terminam num sufixo de `suffixes`."""
    raise NotImplementedError("SPEC-0035: extract_config_refs")


def repository_ref(repo_url):
    """repoURL -> "repository:<owner>/<repo>" quando é de um provedor reconhecível (GitHub); senão None."""
    raise NotImplementedError("SPEC-0035: repository_ref")


def service_and_environment(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL):
    """Application -> (serviço, ambiente): o label quando existe; senão o nome da Application e o namespace de
    destino."""
    raise NotImplementedError("SPEC-0035: service_and_environment")


def map_application(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                    suffixes=DEFAULT_REF_SUFFIXES):
    """Uma Application -> (entidades deployment, service, environment, cluster; relações deploys, runs_in e
    sourced_from)."""
    raise NotImplementedError("SPEC-0035: map_application")


def map_applications(apps, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                     suffixes=DEFAULT_REF_SUFFIXES):
    """Lista de Applications -> (entidades sem chave repetida, relações)."""
    raise NotImplementedError("SPEC-0035: map_applications")


def build_parser():
    parser = argparse.ArgumentParser(prog="argocd.py", description="Coletor argocd da org-atlas")
    parser.add_argument("--from", dest="source", required=True, choices=("argocd", "kubectl"),
                        help="CLI que lê as Applications")
    parser.add_argument("--env-label", default=DEFAULT_ENV_LABEL, help="label do ambiente")
    parser.add_argument("--service-label", default=DEFAULT_SERVICE_LABEL, help="label do serviço")
    parser.add_argument("--ref-suffixes", default=",".join(DEFAULT_REF_SUFFIXES),
                        help="sufixos das chaves de configuração extraídas (a,b)")
    parser.add_argument("--input", default=None, help="arquivo JSON com as Applications em vez da CLI")
    return parser


def main(argv=None):
    build_parser().parse_args(argv)
    raise NotImplementedError("SPEC-0035: argocd.main")


if __name__ == "__main__":
    sys.exit(main())
