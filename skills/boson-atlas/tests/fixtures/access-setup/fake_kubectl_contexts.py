"""kubectl falso da SPEC-0104 (UT-01, UT-02, IT-01): só `config get-contexts -o name`, sem cluster nem rede.

Uso (pelo wrapper `kubectl` que o teste põe no PATH): python3 fake_kubectl_contexts.py <argv do kubectl>...
Ambiente:
    FAKE_KUBECTL_RECORD  arquivo onde cada chamada acrescenta uma linha JSON {"argv": [...]}
    FAKE_KUBECTL_MODE    ok (padrão) | fail (stderr e exit 1) | slow (dorme 30 s antes de responder)
Imprime ctx-dev, ctx-prod e um ARN de cluster EKS com a conta de exemplo 123456789012, um por linha.
"""
import json
import os
import sys
import time

CONTEXTS = ("ctx-dev", "ctx-prod", "arn:aws:eks:us-east-1:123456789012:cluster/dev")


def main(argv):
    record = os.environ.get("FAKE_KUBECTL_RECORD")
    if record:
        with open(record, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv}) + "\n")
    mode = os.environ.get("FAKE_KUBECTL_MODE", "ok")
    if mode == "fail":
        sys.stderr.write("error: kubeconfig falso inválido\n")
        return 1
    if mode == "slow":
        time.sleep(30)
    if argv != ["config", "get-contexts", "-o", "name"]:
        sys.stderr.write("kubectl falso: só config get-contexts -o name\n")
        return 1
    print("\n".join(CONTEXTS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
