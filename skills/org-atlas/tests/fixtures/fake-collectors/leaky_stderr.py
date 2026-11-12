"""Coletor falso (SPEC-0033, revisão G4): escreve um segredo no stderr de um jeito que escapa da máscara por
linha e sai com 1. Os valores são montados em tempo de execução.

Uso: python3 leaky_stderr.py pem   -> chave privada PEM em várias linhas (BEGIN / corpo / END)
     python3 leaky_stderr.py long  -> token logo antes do corte de 500 caracteres da linha
"""
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "pem"
if mode == "pem":
    lines = ["antes-0033",
             "-----BEGIN " + "RSA PRIVATE KEY-----",
             "MIIEow" + "IBAAKCAQEAbodyline0033",
             "c2Vjb25k" + "Ym9keWxpbmUwMDMz",
             "-----END " + "RSA PRIVATE KEY-----",
             "depois-0033"]
else:
    lines = ["antes-0033", "x" * 490 + "ghp_" + "Zx9" * 12 + " fim", "depois-0033"]
for line in lines:
    print(line, file=sys.stderr)
sys.exit(1)
