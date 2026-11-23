"""Máscara de segredos robusta: padrões embutidos casando cada um no texto original e regex com tempo limitado
(SPEC-0092: CH-01, UT-01 e UT-02).
Run: python3 -m unittest discover -s skills/boson-atlas/tests -p test_redaction_robust.py

Contrato esperado de scripts/atlas.py (o Implementer segue estes testes):

    _redact_text(text, extras) -> (masked, count)
        CH-01 (guarda, passa antes): a saída e a contagem dos casos de máscara de hoje (tokens, URL com credencial,
            JWT, PEM/PGP, chave AWS, e-mail e key=value das probes, extra_patterns do time, texto comum) ficam iguais
            ao golden gravado em fixtures/redaction/golden.json. Casos colados ou hostis ficam fora do corpus.
        UT-01: cada padrão embutido casa sozinho no texto original; com dois tokens colados
            (`xoxb-1234567890-ghp_<36 letras>`, `ghp_<30 letras><JWT>`) nenhum pedaço do segundo sobra.
        UT-02: as entradas hostis de 1 MB `"a://:"*200000` e `("eyJ"+"a"*8+".")*80000` são mascaradas em menos de
            2 s cada (rodam num subprocesso com timeout: um travamento falha sem prender a suíte).

Os valores falsos são montados em tempo de execução; o golden guarda só a saída já mascarada. Para regravá-lo (só
quando a mudança de saída for intencional e aprovada): python3 test_redaction_robust.py --record
"""
import json
import subprocess
import sys
import time
import unittest

from helpers import SCRIPT, TESTS, fn

SPEC = "SPEC-0092"
GOLDEN = TESTS / "fixtures" / "redaction" / "golden.json"
LIMIT_SECONDS = 2.0
HANG_TIMEOUT = 10  # o subprocesso é morto aqui: travamento = falha, não suíte presa
TEAM_EXTRA = (r"acme-internal-[0-9]{4}",)


def f(name):
    return fn(name, SPEC)


def _secrets():
    """Os mesmos valores falsos de test_scan.py e test_probe.py, montados por partes."""
    return {
        "ghp": "ghp_" + "Zx9" * 12,
        "gho": "gho_" + "Ab1" * 12,
        "github_pat": "github_pat_" + "A1" * 11 + "_" + "b2c" * 19 + "d2",
        "slack": "xoxb-" + "1234567890" + "-" + "1234567890123" + "-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8",
        "aws": "AKIA" + "IOSFODNN7" + "EXAMPLE",
        "aws_session": "ASIA" + "Q7RT2XW9" + "FAKE0092",
        "rsa": ("-----BEGIN " + "RSA PRIVATE KEY-----\n" + "MIIEow" + "IBAAKCAQEAfake0033\n"
                "c2Vjb25kbGluZWZha2U=\n" + "-----END RSA PRIVATE KEY-----"),
        "pgp": ("-----BEGIN " + "PGP PRIVATE KEY BLOCK-----\n\n" + "lQOYBF" + "pgpbody0033fake\n" + "=AbCd\n"
                + "-----END " + "PGP PRIVATE KEY BLOCK-----"),
        "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjMifQ" + "." + "SflKxwRJSMeKKF2QT4fwpM",
        "password": "s3nh4" + "-fake-" + "0033",
        "email": "maria.silva" + "@" + "acme.example",
        "extra": "acme-internal-" + "4821",
    }


def corpus():
    """[(nome, texto, conjunto de extras)] — os casos de máscara de hoje, sem tokens colados nem entrada hostil."""
    s = _secrets()
    pem_open = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n" + "b3BlbnNzaC1rZXktdjEfake0092\n"
    cases = [
        ("texto comum", "deploy do api em prod às 10h, sem incidente", "none"),
        ("texto vazio", "", "none"),
        ("falso positivo laughs_", "laughs_abcdefghijklmnopqrstuvwxyz", "none"),
        ("falso positivo ASIAPACIFIC", "ASIAPACIFICNORTHEAST1", "none"),
        ("url sem credencial", "veja https://git.acme.example/acme/api.git e ssh://host.example/x", "none"),
        ("ghp sozinho", s["ghp"], "none"),
        ("gho no texto", f"token {s['gho']} expira amanhã", "none"),
        ("github_pat", f"PAT={s['github_pat']}", "none"),
        ("slack", f"bot {s['slack']} no canal", "none"),
        ("aws access key", f"chave {s['aws']} da conta", "none"),
        ("aws session key", f"sessão {s['aws_session']}.", "none"),
        ("rsa private key", f"antes\n{s['rsa']}\ndepois", "none"),
        ("pgp private key", f"antes {s['pgp']} depois", "none"),
        ("pem sem fim", f"chave {pem_open}resto do arquivo", "none"),
        ("jwt", f"Authorization {s['jwt']} ok", "none"),
        ("url com credencial", "clone https://bot:" + s["password"] + "@git.acme.example/acme/api.git agora", "none"),
        ("url usuário vazio", "conecta redis://:" + "r3dis-" + "pw0033" + "@cache:6379 agora", "none"),
        ("url barra na senha", "conecta https://user:" + "p4ss" + "/" + "w0rd0033" + "@host.example/x agora",
         "none"),
        ("url @ na senha", "conecta https://user:" + "p" + "@" + "ss0033" + "@host.example/x agora", "none"),
        ("url duas", "a=https://u1:" + "pw1-0092" + "@h1.example b=postgres://u2:" + "pw2-0092" + "@db:5432/x",
         "none"),
        ("dois segredos separados", f"{s['ghp']} e {s['aws']}", "none"),
        ("vários segredos separados", f"{s['slack']} | {s['jwt']} | {s['github_pat']} | {s['gho']}", "none"),
        ("pontuação _ghp_", "_" + s["ghp"], "none"),
        ("pontuação =ghp_", "=" + s["ghp"], "none"),
        ("pontuação token:ghp_", "token:" + s["ghp"], "none"),
        ("colado a texto, corpo exato", "abc" + s["ghp"] + " fim", "none"),
        ("key=value sem extras", "password=" + "plain-0092" + " user=bot", "none"),
        ("e-mail sem extras", f"contato {s['email']}", "none"),
        ("extra do time", f"id {s['extra']} interno", "team"),
        ("extra do time e token", f"{s['extra']} e {s['ghp']}", "team"),
        ("extra do time sem casar", "acme-internal-xyz", "team"),
        ("probe token= e e-mail", f"login ok token={s['ghp']} para {s['email']}", "probe"),
        ("probe e-mail", f"usuário {s['email']}", "probe"),
        ("probe cpf e cnpj", "cpf 123.456.789-09 cnpj 12.345.678/0001-95", "probe"),
        ("probe bearer", "Authorization: Bearer " + "abc.def-" + "0092fake", "probe"),
        ("probe key=value", "api_key=" + "k3y-0092" + "; secret: " + "s3cr3t-0092" + " pwd=" + "pw-0092",
         "probe"),
        ("probe url e e-mail", "https://bot:" + s["password"] + "@git.acme.example e " + s["email"], "probe"),
        ("probe texto comum", "GET /health 200 em 3ms", "probe"),
    ]
    return cases


def extras_for(kind):
    team = list(f("compile_extra_patterns")(TEAM_EXTRA))
    if kind == "none":
        return []
    if kind == "team":
        return team
    return team + list(f("PROBE_PATTERNS"))


def masked_corpus():
    redact_text = f("_redact_text")
    out = {}
    for name, text, kind in corpus():
        masked, count = redact_text(text, extras_for(kind))
        out[name] = {"extras": kind, "masked": masked, "count": count}
    return out


class GoldenTest(unittest.TestCase):
    def test_today_masking_cases_keep_output_and_count(self):
        """SPEC-0092:CH-01 — os casos de máscara de hoje (tokens, URL com credencial, JWT, PEM/PGP, AWS, e-mail e
        key=value das probes, extras do time, texto comum): saída e contagem de _redact_text iguais ao golden."""
        self.assertTrue(GOLDEN.exists(), f"{GOLDEN} não existe — grave com --record")
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        current = masked_corpus()
        self.assertEqual(sorted(current), sorted(golden), "o corpus e o golden têm os mesmos casos")
        for name in golden:
            with self.subTest(case=name):
                self.assertEqual(current[name], golden[name])

    def test_golden_holds_no_secret(self):
        """SPEC-0092:CH-01 — o golden guarda só a saída mascarada: nenhum valor falso de segredo aparece nele."""
        text = GOLDEN.read_text(encoding="utf-8") if GOLDEN.exists() else ""
        for name, secret in _secrets().items():
            if name in ("email", "extra"):  # só mascarados quando há extras; sem extras aparecem de propósito
                continue
            with self.subTest(secret=name):
                self.assertNotIn(secret, text)


class GluedTokensTest(unittest.TestCase):
    def test_slack_glued_to_github_leaves_no_fragment(self):
        """SPEC-0092:UT-01 — `xoxb-1234567890-ghp_` + 36 letras: nenhum pedaço do token GitHub sobra (antes saía
        [REDACTED]_aaaa…)."""
        body = "a" * 36
        text = "xoxb-1234567890-" + "ghp_" + body
        masked, count = f("_redact_text")(text, [])
        self.assertIn("[REDACTED]", masked)
        self.assertNotIn("aaaa", masked, masked)
        self.assertNotIn("_", masked.replace("[REDACTED]", ""), masked)
        self.assertGreaterEqual(count, 1)

    def test_github_glued_to_jwt_leaves_no_fragment(self):
        """SPEC-0092:UT-01 — `ghp_` + 30 letras seguido de um JWT: nem o payload nem a assinatura do JWT sobram
        (antes ficavam à mostra)."""
        payload, signature = "eyJ" + "zdWIiOiIxMjMifQ", "SflKxwRJSMeKKF2QT4fwpM"
        jwt = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + payload + "." + signature
        text = "ghp_" + "b" * 30 + jwt
        masked, count = f("_redact_text")(text, [])
        self.assertIn("[REDACTED]", masked)
        for fragment in (payload, signature, "zdWIi", "SflKx", "bbbb"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, masked, masked)
        self.assertNotIn(".", masked, masked)
        self.assertGreaterEqual(count, 1)


def _b64url(seed, size):
    """Um corpo base64url falso de `size` caracteres, montado em tempo de execução."""
    return (seed * (size // len(seed) + 1))[:size]


def _oversized_cases():
    """[(nome, texto, segredos que não podem sobrar, saída esperada)] — Emenda v2: JWT e credencial de URL acima
    dos limites da rodada 1. A saída esperada é a que o _redact_text da `main` (6764f6f^) produz para o mesmo texto
    (diferencial gravado à mão: nada que a `main` mascara pode deixar de ser mascarado)."""
    payload = "eyJ" + _b64url("Ab9_-", 9000 - 3)
    signature = "Sig_" + _b64url("x7Q-", 40)
    big_header = "eyJ" + _b64url("hbG", 1100 - 3)
    user = _b64url("u5r", 300)
    token300, token2000 = _b64url("T0k", 300), _b64url("T0k", 2000)
    password = "pw-" + "0092"
    return [
        ("bearer com payload de 9000",
         "Authorization: Bearer " + "eyJ" + "hbGciOiJIU" + "." + payload + "." + signature,
         (payload, signature), "Authorization: Bearer [REDACTED]"),
        ("jwt com header de 1100",
         big_header + "." + "eyJ" + "zdWIiOiIxMjMifQ" + "." + "SflKxwRJSMeKKF2QT4fwpM",
         (big_header, "SflKxwRJSMeKKF2QT4fwpM"), "[REDACTED]"),
        ("url com senha de 300", "clone https://oauth2:" + token300 + "@gitlab.example.com/x.git ok",
         (token300,), "clone https://oauth2:[REDACTED]@gitlab.example.com/x.git ok"),
        ("url com senha de 2000", "clone https://oauth2:" + token2000 + "@gitlab.example.com/x.git ok",
         (token2000,), "clone https://oauth2:[REDACTED]@gitlab.example.com/x.git ok"),
        ("url com usuário de 300", "clone https://" + user + ":" + password + "@gitlab.example.com/x.git ok",
         (password,), "clone https://" + user + ":[REDACTED]@gitlab.example.com/x.git ok"),
    ]


class OversizedSecretsTest(unittest.TestCase):
    def test_oversized_secrets_leave_no_fragment(self):
        """SPEC-0092:UT-01 — Emenda v2: JWT com payload de 9000 ou header de 1100 caracteres e credencial de URL com
        senha de 300 ou 2000 ou usuário de 300: nenhum pedaço de 16 caracteres do segredo sobra."""
        redact_text = f("_redact_text")
        for name, text, secrets, _ in _oversized_cases():
            with self.subTest(case=name):
                masked, count = redact_text(text, [])
                self.assertIn("[REDACTED]", masked)
                self.assertGreaterEqual(count, 1)
                for secret in secrets:
                    width = min(16, len(secret))
                    leaked = [i for i in range(len(secret) - width + 1) if secret[i:i + width] in masked]
                    self.assertEqual(leaked, [], f"{name}: pedaço do segredo sobrou: {masked[:120]!r}")

    def test_oversized_secrets_match_main_masking(self):
        """SPEC-0092:UT-01 — Emenda v2 (diferencial): para esses casos a saída e a contagem são as do _redact_text
        da `main` (só a senha da URL é mascarada; o JWT inteiro)."""
        redact_text = f("_redact_text")
        for name, text, _, expected in _oversized_cases():
            with self.subTest(case=name):
                masked, count = redact_text(text, [])
                self.assertEqual(masked, expected, f"{name}: {masked[:120]!r}")
                self.assertEqual(count, 1)


CHILD = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("atlas", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
text = {expr}
start = time.perf_counter()
masked, count = module._redact_text(text, [])
elapsed = time.perf_counter() - start
print(json.dumps({{"elapsed": elapsed, "size": len(text), "count": count}}))
"""


class HostileInputTest(unittest.TestCase):
    def run_hostile(self, expr):
        code = CHILD.format(expr=expr)
        wall = time.monotonic()
        try:
            result = subprocess.run([sys.executable, "-c", code, str(SCRIPT)], capture_output=True, text=True, check=False,
                                    timeout=HANG_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.fail(f"{expr}: a máscara não terminou em {HANG_TIMEOUT} s (limite {LIMIT_SECONDS} s)")
        wall = time.monotonic() - wall
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreaterEqual(data["size"], 900_000)  # ~1 MB
        self.assertLess(data["elapsed"], LIMIT_SECONDS,
                        f"{expr}: {data['elapsed']:.2f} s na máscara (subprocesso: {wall:.2f} s)")

    def test_hostile_url_input_is_masked_in_bounded_time(self):
        """SPEC-0092:UT-02 — `"a://:"*200000` (1 MB): a máscara termina em menos de 2 s (antes passava de 60 s)."""
        self.run_hostile('"a://:" * 200000')

    def test_hostile_jwt_input_is_masked_in_bounded_time(self):
        """SPEC-0092:UT-02 — `("eyJ"+"a"*8+".")*80000` (1 MB): a máscara termina em menos de 2 s (antes ~25 s)."""
        self.run_hostile('("eyJ" + "a" * 8 + ".") * 80000')


def record():
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(masked_corpus(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(f"gravado {GOLDEN}")


if __name__ == "__main__":
    if "--record" in sys.argv:
        record()
    else:
        unittest.main()
