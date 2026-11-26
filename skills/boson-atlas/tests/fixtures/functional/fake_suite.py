"""Suíte de testes falsa (SPEC-0103): grava o próprio argv, o ambiente e a pasta de trabalho e sai com o código pedido,
sem rede e sem ferramenta de teste de verdade. Os testes a põem no arquivo de jornadas do adaptador suite.

Uso: python3 fake_suite.py --record <arquivo> [--exit <n>] [--step <texto>]... [--noise <texto>]...
                           [--sleep <segundos>] [--child-pid <arquivo>] [qualquer outro argumento]
    --record      acrescenta ao <arquivo> uma linha JSON {"argv": [...], "env": {...}, "cwd": "..."}
    --step        imprime "ATLAS-FAILED-STEP: <texto>" (o protocolo do adaptador), na ordem
    --noise       imprime <texto> como uma linha qualquer (stdout e stderr), fora do protocolo
    --sleep       dorme antes de sair
    --child-pid   abre um processo filho que dorme 60 s e grava o pid dele no <arquivo> (o teste confere que o
                  adaptador encerra o grupo inteiro no tempo esgotado)
    --exit        o código de saída (padrão 0)
Argumentos desconhecidos são ignorados e só ficam no registro (o teste confere que chegam como estão, sem shell).
"""
import json
import os
import subprocess
import sys
import time


def values(argv, name):
    return [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == name]


def main(argv):
    record = values(argv, "--record")
    if record:
        with open(record[0], "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}) + "\n")
    for text in values(argv, "--noise"):
        print(text)
        print(text, file=sys.stderr)
    for text in values(argv, "--step"):
        print(f"ATLAS-FAILED-STEP: {text}")
    sys.stdout.flush()
    for path in values(argv, "--child-pid"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
    for seconds in values(argv, "--sleep"):
        time.sleep(float(seconds))
    code = values(argv, "--exit")
    return int(code[0]) if code else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
