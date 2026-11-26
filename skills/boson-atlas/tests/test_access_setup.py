"""`atlas.py access setup`: o onboarding do acesso local (SPEC-0104: UT-01 a UT-05 e IT-01; ADR-0025, ADR-0010).

Contrato (seção 6 da SPEC-0104) que estes testes fixam:

    atlas.py access setup [--atlas X]                      interativo (exige terminal no stdin)
    atlas.py access setup [--atlas X] [--dry-run] [--cluster <cluster>=<contexto>]... [--cloud <ambiente>=<profile>]...
        [--db-user|--db-name|--db-passfile <datastore>=<valor>]... [--base-url <ambiente>=<url>]...
    ordem: configuração local (3) · graph.json (2 "sem graph.json: rode atlas.py build") · nomes do grafo (2 "<tipo>
        <nome> não está no atlas"; fora da regra "opção --cloud: item <i> inválido — nome fora da regra") · valores
        pelas regras de access.* (2 "--cloud: item <i> inválido — <motivo>", sem o valor; "datastore <id>: faltam
        <campos>") · grava (ou, com --dry-run, só o resumo) e sai com 0.
    perguntas, nesta ordem e só para o que o grafo usa: contexto por cluster de algum deployment · profile por ambiente
        com recurso ligado a deployment · URL base por ambiente tier: test · usuário, banco e arquivo de senhas por
        datastore postgres/aurora-postgresql; "já definido — Enter mantém, '-' apaga, ou digite outro"; inválida
        repete com o motivo até 3 vezes e pula; "Gravar? [s/N]" (só s/sim grava; senão "nada gravado", exit 0).
    resumo: "access.<bloco>.<nome>: definido | não definido | mantido | apagado", nunca o valor.
    detecção: ["kubectl", "config", "get-contexts", "-o", "name"] (timeout 10 s) e as seções de AWS_CONFIG_FILE ou
        ~/.aws/config ([default] -> default, [profile x] -> x); o arquivo de credenciais nunca é aberto.
    avisos: "arquivo de senhas de <datastore> não encontrado"; "arquivo de senhas de <datastore> legível por outros:
        o psql ignora (use chmod 600)".

Leituras desta suíte (listadas no relatório do test-writer):
    - O modo interativo lê as respostas linha a linha do stdin (um terminal) e escreve as perguntas no stdout; o teste
      roda o atlas.py de verdade com o stdin num pseudo-terminal (pty, sem eco) e as respostas já escritas.
    - Cada pergunta começa com "Qual "; a lista de detectados é numerada ("1) <nome> 2) <nome>") na mesma pergunta e
      "1" escolhe o nome marcado com 1).
    - No modo não interativo, o que já está na entrada e não veio nas opções fica como está ("mantido" no resumo);
      as opções de um datastore se somam aos campos que ele já tem.
    - Enter na pergunta do usuário do banco pode pular só o usuário ou o bloco todo: o teste não depende disso (as
      respostas que sobram caem no "Gravar?" como Enter = não).

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); KUBECONFIG, AWS_CONFIG_FILE e
AWS_SHARED_CREDENTIALS_FILE nunca apontam para os reais; o PATH só tem o kubectl falso (fixtures/access-setup/) e
pastas sem kubectl; sem AWS CLI, psql nem rede. Nomes genéricos (acme, globex, api, orders, dev, prod) e a conta de
exemplo 123456789012.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import unittest

from helpers import SCRIPT, TESTS, Sandbox, fn, output
from test_probe import adapter_yaml, probes_yaml
from test_probe_resource import access_text

SPEC = "SPEC-0104"
FIXTURES = TESTS / "fixtures" / "access-setup"
SETUP_ATLAS = FIXTURES / "atlas"
FAKE_KUBECTL = FIXTURES / "fake_kubectl_contexts.py"
AWS_CONFIG = FIXTURES / "aws-config"
FACTS = FIXTURES / "facts.json"
FAKE_MESSAGING = TESTS / "fixtures" / "probe-stats" / "fake_messaging.py"

CONTEXTS = ("ctx-dev", "ctx-prod", "arn:aws:eks:us-east-1:123456789012:cluster/dev")
KUBECTL_ARGV = ["config", "get-contexts", "-o", "name"]
ACCOUNT = "123456789012"
OLD_PROD_CONTEXT = "ctx-old-prod-0104"
BASE_URL = "https://dev.acme.example"
NO_TTY = "access setup interativo precisa de um terminal; use --cluster, --cloud, --base-url ou --db-*"
# "orders" é também o nome da fila e o prefixo do datastore: como nome de banco ele nunca aparece como valor
DB_NAME_SHOWN = re.compile(r"""(database|name|banco)["']?\s*[:=]\s*["']?orders\b""", re.IGNORECASE)


def f(name):
    return fn(name, SPEC)


def clean_path():
    """As pastas do PATH sem nenhum kubectl (nunca o kubectl de verdade)."""
    folders = []
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder and not os.path.exists(os.path.join(folder, "kubectl")):
            folders.append(folder)
    return os.pathsep.join(folders)


def segments(text):
    """O stdout do modo interativo cortado em perguntas (cada uma começa com "Qual ")."""
    return [part for part in re.split(r"(?=Qual )", text) if part.startswith("Qual ")]


def segment(text, needle):
    found = [part for part in segments(text) if needle in part]
    if not found:
        raise AssertionError(f"nenhuma pergunta com {needle!r} na saída:\n{text}")
    return found[0]


class SetupCase(unittest.TestCase):
    """Um atlas temporário (cópia de fixtures/access-setup/atlas), o kubectl falso num bin/ próprio, o .aws/config e
    um .aws/credentials sem permissão de leitura no HOME temporário e um arquivo de senhas 0600."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(SETUP_ATLAS, self.box.atlas)
        self.bin = self.box.root / "bin"
        self.bin.mkdir()
        wrapper = self.bin / "kubectl"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_KUBECTL}" "$@"\n', encoding="utf-8")
        os.chmod(wrapper, 0o755)
        self.kubectl_record = self.box.root / "kubectl-calls.jsonl"
        aws = self.box.home / ".aws"
        aws.mkdir()
        shutil.copy(AWS_CONFIG, aws / "config")
        self.credentials = aws / "credentials"
        self.credentials.write_text("[default]\naws_access_key_id = FALSO\n", encoding="utf-8")
        os.chmod(self.credentials, 0)
        self.addCleanup(os.chmod, self.credentials, 0o600)
        secrets = self.box.root / "secrets"
        secrets.mkdir()
        self.passfile = secrets / ".pgpass-0104"
        self.passfile.write_text("*:*:orders:reader:senha-falsa-0104\n", encoding="utf-8")
        os.chmod(self.passfile, 0o600)
        self.config = self.box.config_home / "config.yml"

    # ------------------------------------------------------------------ montagem

    def configure(self, access=None, extra=""):
        self.box.write_local(f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n"
                             + access_text(access or {}) + extra)

    def environ(self, kubectl=True, mode="ok", aws_config_file=None):
        env = dict(os.environ)
        for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_PROFILE", "ATLAS_NAME"):
            env.pop(name, None)
        env.update({"HOME": str(self.box.home), "XDG_CONFIG_HOME": str(self.box.home / ".config"),
                    "ATLAS_CONFIG_HOME": str(self.box.config_home),
                    "KUBECONFIG": str(self.box.root / "kubeconfig-falso-inexistente"),
                    "PATH": (str(self.bin) + os.pathsep if kubectl else "") + clean_path(),
                    "FAKE_KUBECTL_RECORD": str(self.kubectl_record), "FAKE_KUBECTL_MODE": mode})
        if aws_config_file is not None:
            env["AWS_CONFIG_FILE"] = str(aws_config_file)
        return env

    # ------------------------------------------------------------------ execução

    def run_atlas(self, *args, **kw):
        """atlas.py como processo, com o stdin fechado (nunca um terminal)."""
        result = subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False,
                                cwd=self.box.root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env=self.environ(**kw), timeout=120)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def setup_with(self, *options, **kw):
        return self.run_atlas("access", "setup", *options, **kw)

    def run_tty(self, answers, *args, timeout=60, **kw):
        """`access setup` interativo: o stdin é um pseudo-terminal (sem eco) com `answers` já escritas, uma por
        linha; devolve (exit, stdout, stderr)."""
        import pty
        import termios

        master, slave = pty.openpty()
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "access", "setup", *[str(a) for a in args]],
                                cwd=self.box.root, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self.environ(**kw))
        os.close(slave)
        try:
            os.write(master, "".join(f"{answer}\n" for answer in answers).encode("utf-8"))
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                self.fail(f"access setup interativo não terminou (esperando resposta?):\n{out}\n{err}")
        finally:
            os.close(master)
        self.assertNotIn("Traceback", out + err, out + err)
        return proc.returncode, out, err

    def entry(self, name=None):
        data = fn("read_yaml")(self.config)
        if "atlases" in data:
            return data["atlases"][name or data.get("default")]
        return data

    def kubectl_calls(self):
        if not self.kubectl_record.exists():
            return []
        return [json.loads(line)["argv"] for line in self.kubectl_record.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def assertNoValue(self, text, values):
        low = text.lower()
        for value in values:
            self.assertNotIn(str(value).lower(), low, f"valor de acesso apareceu: {value}")
        self.assertIsNone(DB_NAME_SHOWN.search(text), "o nome do banco apareceu")
        self.assertNotIn(ACCOUNT, text)


# --------------------------------------------------------------------------- UT-01


class DetectionTest(SetupCase):
    ENTERS = [""] * 12  # pula tudo; o que sobra cai no "Gravar?" (Enter = não)

    def test_contexts_and_profiles_are_detected_by_name_only(self):
        """SPEC-0104:UT-01 — kubectl falso com 3 contextos e ~/.aws/config com [default], [profile dev-ro] e
        [sso-session x]: a pergunta do cluster lista os 3 contextos, a do profile só default e dev-ro; o argv do
        kubectl é exatamente config get-contexts -o name; o .aws/credentials sem leitura não atrapalha."""
        # SPEC-0104:UT-01
        self.configure()
        code, out, err = self.run_tty(self.ENTERS)
        self.assertEqual(code, 0, out + err)
        calls = self.kubectl_calls()
        self.assertTrue(calls, "o kubectl não foi chamado")
        self.assertTrue(all(argv == KUBECTL_ARGV for argv in calls), calls)
        cluster = segment(out, "cluster cluster-dev")
        for number in ("1)", "2)", "3)"):  # o terceiro é o ARN: o teste não exige que ele apareça por inteiro
            self.assertIn(number, cluster)
        for context in CONTEXTS[:2]:
            self.assertIn(context, cluster)
        profile = segment(out, "profile da AWS")
        self.assertIn("default", profile)
        self.assertIn("dev-ro", profile)
        self.assertIn("2)", profile)
        self.assertNotIn("3)", profile, "uma seção que não é profile virou sugestão")
        self.assertIn("nada gravado", out + err)

    def test_aws_config_file_variable_is_used(self):
        """SPEC-0104:UT-01 — AWS_CONFIG_FILE vale no lugar de ~/.aws/config."""
        # SPEC-0104:UT-01
        self.configure()
        os.chmod(self.credentials, 0o600)
        (self.box.home / ".aws" / "config").unlink()
        moved = self.box.root / "aws-config-movido"
        moved.write_text("[profile qa-ro]\nregion = us-east-1\n", encoding="utf-8")
        code, out, err = self.run_tty(self.ENTERS, aws_config_file=moved)
        self.assertEqual(code, 0, out + err)
        profile = segment(out, "profile da AWS")
        self.assertIn("qa-ro", profile)
        self.assertNotIn("2)", profile)

    def test_without_tools_the_questions_have_no_suggestion(self):
        """SPEC-0104:UT-01 — sem kubectl no PATH, com kubectl que sai com 1 e sem arquivo da AWS: as perguntas saem
        sem sugestão e sem erro."""
        # SPEC-0104:UT-01
        self.configure()
        (self.box.home / ".aws" / "config").unlink()
        for label, kw in (("sem kubectl", {"kubectl": False}), ("kubectl com erro", {"mode": "fail"})):
            with self.subTest(label):
                code, out, err = self.run_tty(self.ENTERS, **kw)
                self.assertEqual(code, 0, out + err)
                self.assertNotIn("1)", segment(out, "cluster cluster-dev"))
                self.assertNotIn("1)", segment(out, "profile da AWS"))
                self.assertNotIn("ctx-dev", out)

    def test_slow_kubectl_times_out_in_10_seconds(self):
        """SPEC-0104:UT-01 — kubectl que dorme 30 s: o setup desiste em ~10 s e pergunta sem sugestão."""
        # SPEC-0104:UT-01
        self.configure()
        started = time.monotonic()
        code, out, err = self.run_tty(self.ENTERS, mode="slow")
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0, out + err)
        self.assertLess(elapsed, 25, "o timeout de 10 s do kubectl não foi aplicado")
        self.assertNotIn("1)", segment(out, "cluster cluster-dev"))


# --------------------------------------------------------------------------- UT-02


class InteractiveTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.configure({"clusters": {"cluster-prod": {"context": OLD_PROD_CONTEXT}}})

    def test_questions_answers_and_save(self):
        """SPEC-0104:UT-02 — as perguntas na ordem do contrato (contexto por cluster, profile de dev, URL base de dev,
        usuário, banco e arquivo de senhas de orders-db), só para o que o grafo usa; "1" escolhe o primeiro detectado,
        "-" apaga o já definido (sem mostrar o valor), um nome digitado vale, três URLs inválidas pulam o item com o
        motivo a cada vez, e "s" grava."""
        # SPEC-0104:UT-02
        answers = ["1", "-", "dev-ro", "ftp://a.example", "ftp://b.example", "ftp://c.example", "reader", "orders",
                   str(self.passfile), "s"]
        code, out, err = self.run_tty(answers)
        self.assertEqual(code, 0, out + err)
        texts = ["Qual o contexto do kubectl do cluster cluster-dev", "Qual o contexto do kubectl do cluster cluster-prod",
                 "Qual profile da AWS você usa no ambiente dev", "Qual a URL base do ambiente dev",
                 "Qual usuário só de leitura do banco orders-db", "Qual o nome do banco",
                 "Qual o arquivo de senhas (.pgpass)", "Gravar? [s/N]"]
        positions = [out.find(text) for text in texts]
        self.assertNotIn(-1, positions, dict(zip(texts, positions)))
        self.assertEqual(positions[2:], sorted(positions[2:]), "fora da ordem do contrato")
        self.assertLess(max(positions[:2]), positions[2])
        self.assertIn("só de leitura", segment(out, "profile da AWS"))
        for absent in ("ambiente prod", "banco cache", "cluster cluster-x"):
            self.assertNotIn(absent, out)
        prod = segment(out, "cluster cluster-prod")
        self.assertIn("já definido", prod)
        self.assertNotIn(OLD_PROD_CONTEXT, out + err)
        self.assertGreaterEqual((out + err).count("precisa ser http ou https absoluta"), 3, out + err)
        first = re.search(r"1\) (\S+)", segment(out, "cluster cluster-dev"))
        self.assertIsNotNone(first, "sem a lista numerada de detectados")
        self.assertIn(first.group(1), CONTEXTS)
        for line in ("access.clusters.cluster-dev: definido", "access.clusters.cluster-prod: apagado",
                     "access.cloud.dev: definido", "access.urls.dev: não definido",
                     "access.databases.orders-db: definido"):
            self.assertIn(line, out)
        after_question = out[positions[-1]:]
        self.assertNoValue(after_question + err, ["dev-ro", "reader", str(self.passfile), OLD_PROD_CONTEXT])
        access = self.entry()["access"]
        self.assertEqual(access["clusters"], {"cluster-dev": {"context": first.group(1)}})
        self.assertEqual(access["cloud"], {"dev": {"profile": "dev-ro"}})
        self.assertFalse(access.get("urls"), access)
        self.assertEqual(access["databases"], {"orders-db": {"user": "reader", "database": "orders",
                                                             "passfile": str(self.passfile)}})
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_no_keeps_the_file(self):
        """SPEC-0104:UT-02 — Enter pula (e mantém o já definido) e "N" no "Gravar?" não muda o arquivo: exit 0 e "nada
        gravado"."""
        # SPEC-0104:UT-02
        before = self.config.read_bytes()
        answers = ["", "", "", BASE_URL, "reader", "orders", str(self.passfile), "N"]
        code, out, err = self.run_tty(answers)
        self.assertEqual(code, 0, out + err)
        self.assertIn("nada gravado", out + err)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn("access.clusters.cluster-prod: mantido", out)
        self.assertIn("access.clusters.cluster-dev: não definido", out)
        self.assertIn("access.urls.dev: definido", out)
        self.assertNoValue(out[out.find("Gravar?"):] + err, [BASE_URL, "reader", str(self.passfile)])


# --------------------------------------------------------------------------- UT-03 e UT-04


def full_options(passfile):
    return ["--cluster", "cluster-dev=ctx-dev", "--cloud", "dev=dev-ro", "--base-url", f"dev={BASE_URL}",
            "--db-user", "orders-db=reader", "--db-name", "orders-db=orders", "--db-passfile",
            f"orders-db={passfile}"]


class NonInteractiveTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.other = self.box.root / "work" / "globex-atlas"
        shutil.copytree(SETUP_ATLAS, self.other)
        probes = probes_yaml([adapter_yaml("fake", [sys.executable, str(self.box.root / "nao-existe.py")])],
                             enabled=False, indent="    ")
        self.box.write_local(
            "default: acme\n"
            "atlases:\n"
            "  acme:\n"
            f"    atlas: {json.dumps(str(self.box.atlas))}\n"
            "    credentials: {github: {env: [ACME_GITHUB_TOKEN]}}\n"
            "    access:\n"
            "      clusters:\n"
            f"        cluster-prod: {{context: {json.dumps(OLD_PROD_CONTEXT)}}}\n"
            + probes +
            "  globex:\n"
            f"    atlas: {json.dumps(str(self.other))}\n"
            "    credentials: {}\n"
            "    access:\n"
            "      clusters:\n"
            "        cluster-dev: {context: \"ctx-globex-0104\"}\n")
        self.before = fn("read_yaml")(self.config)

    def assertRefused(self, result, text, code=2):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("unrecognized arguments", output(result))
        self.assertIn(text, output(result))

    def test_options_write_only_access(self):
        """SPEC-0104:UT-03 — as opções gravam os quatro blocos em access de acme, mantêm atlas, credentials, probes, o
        cluster já definido e a entrada globex, e o arquivo fica 0600; o resumo diz só definido/mantido."""
        # SPEC-0104:UT-03
        result = self.setup_with(*full_options(self.passfile))
        self.assertEqual(result.returncode, 0, output(result))
        data = fn("read_yaml")(self.config)
        self.assertEqual(data["default"], self.before["default"])
        self.assertEqual(data["atlases"]["globex"], self.before["atlases"]["globex"])
        acme, old = data["atlases"]["acme"], self.before["atlases"]["acme"]
        for key in ("atlas", "credentials", "probes"):
            self.assertEqual(acme[key], old[key], key)
        self.assertEqual(set(acme), set(old))
        self.assertEqual(acme["access"], {
            "clusters": {"cluster-prod": {"context": OLD_PROD_CONTEXT}, "cluster-dev": {"context": "ctx-dev"}},
            "cloud": {"dev": {"profile": "dev-ro"}},
            "urls": {"dev": {"base_url": BASE_URL}},
            "databases": {"orders-db": {"user": "reader", "database": "orders", "passfile": str(self.passfile)}},
        })
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        for line in ("access.clusters.cluster-dev: definido", "access.clusters.cluster-prod: mantido",
                     "access.cloud.dev: definido", "access.urls.dev: definido",
                     "access.databases.orders-db: definido"):
            self.assertIn(line, result.stdout)

    def test_names_outside_the_atlas(self):
        """SPEC-0104:UT-03 — cluster, ambiente ou datastore que o grafo não tem: exit 2 "<tipo> <nome> não está no
        atlas" e nada gravado; nome fora da regra: "opção --cloud: item 1 inválido — nome fora da regra"."""
        # SPEC-0104:UT-03
        before = self.config.read_bytes()
        cases = [
            (["--cloud", "qa=x"], "ambiente qa não está no atlas"),
            (["--base-url", f"qa={BASE_URL}"], "ambiente qa não está no atlas"),
            (["--cluster", "cluster-x=ctx"], "cluster cluster-x não está no atlas"),
            (["--db-user", "nope-db=r", "--db-name", "nope-db=d", "--db-passfile", f"nope-db={self.passfile}"],
             "datastore nope-db não está no atlas"),
            (["--cloud", "q a=x"], "opção --cloud: item 1 inválido — nome fora da regra"),
        ]
        for options, text in cases:
            with self.subTest(options=options):
                self.assertRefused(self.setup_with(*options), text)
                self.assertEqual(self.config.read_bytes(), before)

    def test_invalid_values_never_echo(self):
        """SPEC-0104:UT-03 — quebra de linha, vazio, mais de 256 caracteres, URL base com usuário e senha ou fora de
        http(s): exit 2 com a opção, a posição e o motivo, nunca o valor."""
        # SPEC-0104:UT-03
        before = self.config.read_bytes()
        long_user = "u" * 300
        cases = [
            (["--cloud", "dev=ok-ro", "--cloud", "prod=perfil\nquebrado"], "--cloud: item 2 inválido —",
             "quebra de linha", "perfil"),
            (["--cluster", "cluster-dev="], "--cluster: item 1 inválido —", "vazio", None),
            (["--db-user", f"orders-db={long_user}", "--db-name", "orders-db=orders", "--db-passfile",
              f"orders-db={self.passfile}"], "--db-user: item 1 inválido —", "256", long_user),
            (["--base-url", "dev=https://u:segredo-0104@dev.acme.example"], "--base-url: item 1 inválido —",
             "com usuário ou senha", "segredo-0104"),
            (["--base-url", "dev=ftp://dev.acme.example"], "--base-url: item 1 inválido —",
             "precisa ser http ou https absoluta", "ftp://"),
        ]
        for options, head, reason, value in cases:
            with self.subTest(options=options[:2]):
                result = self.setup_with(*options)
                self.assertRefused(result, head)
                self.assertIn(reason, output(result))
                if value:
                    self.assertNotIn(value, output(result))
                self.assertNotIn("ok-ro", output(result))
                self.assertEqual(self.config.read_bytes(), before)

    def test_incomplete_database(self):
        """SPEC-0104:UT-03 — --db-user sozinho, sem os outros campos na entrada: exit 2 "datastore orders-db: faltam
        database, passfile"; com o datastore já completo na entrada, --db-user sozinho troca só o usuário."""
        # SPEC-0104:UT-03
        before = self.config.read_bytes()
        result = self.setup_with("--db-user", "orders-db=reader")
        self.assertRefused(result, "datastore orders-db: faltam database, passfile")
        self.assertNotIn("reader", output(result))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.setup_with(*full_options(self.passfile)).returncode, 0)
        result = self.setup_with("--db-user", "orders-db=reader2")
        self.assertEqual(result.returncode, 0, output(result))
        self.assertEqual(self.entry("acme")["access"]["databases"],
                         {"orders-db": {"user": "reader2", "database": "orders", "passfile": str(self.passfile)}})

    def test_dry_run_keeps_the_file(self):
        """SPEC-0104:UT-03 — --dry-run mostra o resumo e deixa o config.yml igual byte a byte."""
        # SPEC-0104:UT-03
        before = self.config.read_bytes()
        result = self.setup_with("--dry-run", *full_options(self.passfile))
        self.assertEqual(result.returncode, 0, output(result))
        self.assertIn("access.cloud.dev: definido", result.stdout)
        self.assertIn("access.databases.orders-db: definido", result.stdout)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertNoValue(output(result), ["ctx-dev", "dev-ro", BASE_URL, "reader", str(self.passfile)])

    def test_without_terminal_graph_or_config(self):
        """SPEC-0104:UT-03 — sem opções e sem terminal: exit 2 com a mensagem do contrato; sem graph.json: exit 2
        "sem graph.json: rode atlas.py build"; sem configuração local: exit 3."""
        # SPEC-0104:UT-03
        self.assertRefused(self.setup_with(), NO_TTY)
        (self.box.atlas / "graph.json").unlink()
        self.assertRefused(self.setup_with("--cloud", "dev=dev-ro"), "sem graph.json: rode atlas.py build")
        self.config.unlink()
        self.assertRefused(self.setup_with("--cloud", "dev=dev-ro"), "", code=3)

    def test_values_never_shown_after_writing(self):
        """SPEC-0104:UT-04 — depois de gravar, access setup, config, config --json, doctor, doctor --json, probes stats
        --json e o probes.log não mostram contexto, profile, URL base, usuário, banco nem o arquivo de senhas."""
        # SPEC-0104:UT-04
        values = ["ctx-dev", "dev-ro", BASE_URL, "reader", str(self.passfile), self.passfile.name, OLD_PROD_CONTEXT]
        texts = [output(self.setup_with(*full_options(self.passfile)))]
        for args in (("config",), ("config", "--json"), ("doctor",), ("doctor", "--json"),
                     ("probes", "stats", "--json")):
            result = self.run_atlas(*args)
            self.assertIn(result.returncode, (0, 1), f"{args}: {output(result)}")
            texts.append(output(result))
        config_json = json.loads(texts[2])
        self.assertIn("definido", json.dumps(config_json, ensure_ascii=False))
        log = self.box.config_home / "probes.log"
        if log.exists():
            texts.append(log.read_text(encoding="utf-8"))
        for text in texts:
            self.assertNoValue(text, values)


# --------------------------------------------------------------------------- UT-05


class PassfileTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.configure()

    def db_options(self, passfile):
        return ["--db-user", "orders-db=reader", "--db-name", "orders-db=orders", "--db-passfile",
                f"orders-db={passfile}"]

    def test_missing_passfile_warns_and_writes(self):
        """SPEC-0104:UT-05 — arquivo de senhas que não existe: avisa "arquivo de senhas de orders-db não encontrado" e
        grava."""
        # SPEC-0104:UT-05
        missing = self.box.root / "secrets" / "nao-existe.pgpass"
        result = self.setup_with(*self.db_options(missing))
        self.assertEqual(result.returncode, 0, output(result))
        self.assertIn("arquivo de senhas de orders-db não encontrado", output(result))
        self.assertEqual(self.entry()["access"]["databases"]["orders-db"]["passfile"], str(missing))
        self.assertNotIn(str(missing), output(result))

    def test_open_passfile_warns_without_reading(self):
        """SPEC-0104:UT-05 — arquivo legível por outros (0044, sem leitura para o dono): avisa "legível por outros: o
        psql ignora (use chmod 600)", grava e não falha (o arquivo nunca é aberto)."""
        # SPEC-0104:UT-05
        os.chmod(self.passfile, 0o044)
        self.addCleanup(os.chmod, self.passfile, 0o600)
        result = self.setup_with(*self.db_options(self.passfile))
        self.assertEqual(result.returncode, 0, output(result))
        self.assertIn("arquivo de senhas de orders-db legível por outros: o psql ignora (use chmod 600)",
                      output(result))
        self.assertNotIn("Permission", output(result))
        self.assertNotIn("senha-falsa-0104", output(result))
        self.assertEqual(self.entry()["access"]["databases"]["orders-db"]["passfile"], str(self.passfile))


# --------------------------------------------------------------------------- IT-01


class IntegrationTest(SetupCase):
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.box.atlas)
        self.messaging_record = self.box.root / "messaging-calls.jsonl"

    def build_atlas(self):
        out = self.box.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        inputs = self.box.atlas.parent / "inputs"
        inputs.mkdir(exist_ok=True)
        shutil.copy(FACTS, inputs / "facts.json")
        command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/../inputs/facts.json",
                   "--category", "delivery"]
        shared = (SETUP_ATLAS / "atlas-config.yml").read_text(encoding="utf-8").replace(
            "collectors: []\n", "collectors:\n  - id: facts\n    category: delivery\n    command: ["
            + ", ".join(json.dumps(a) for a in command) + "]\n")
        (self.box.atlas / "atlas-config.yml").write_text(shared, encoding="utf-8")
        adapter = adapter_yaml("fakemsg", [sys.executable, str(FAKE_MESSAGING), "--record",
                                           str(self.messaging_record), "--adapter", "fakemsg"],
                               verbs=("queue",), timeout=10)
        self.box.write_local(f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n"
                             + probes_yaml([adapter]))
        for step in ("scan", "build"):
            result = self.run_atlas(step)
            self.assertEqual(result.returncode, 0, f"{step}: {output(result)}")

    def test_refusal_metric_setup_and_probe(self):
        """SPEC-0104:IT-01 — probe recusada por falta de access.cloud (exit 4) → doctor e probes stats contam a recusa
        → access setup --cloud dev=dev-ro grava → a mesma probe passa e o adaptador recebe target.cloud.profile;
        nenhuma saída mostra dev-ro."""
        # SPEC-0104:IT-01
        self.build_atlas()
        probe = ("probe", "messaging", "queue", "--service", "api", "--env", "dev", "--resource", "queue:orders")
        texts = []
        refused = self.run_atlas(*probe)
        texts.append(output(refused))
        self.assertEqual(refused.returncode, 4, output(refused))
        self.assertIn("sem acesso local: cloud", output(refused))
        doctor = self.run_atlas("doctor")
        texts.append(output(doctor))
        self.assertIn("AVISO uso das probes — 1 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py "
                      "access setup", doctor.stdout)
        stats = self.run_atlas("probes", "stats", "--json")
        texts.append(output(stats))
        self.assertEqual(stats.returncode, 0, output(stats))
        self.assertEqual(json.loads(stats.stdout)["no_access"]["cloud"], 1)
        setup = self.setup_with("--cloud", "dev=dev-ro")
        texts.append(output(setup))
        self.assertEqual(setup.returncode, 0, output(setup))
        passed = self.run_atlas(*probe)
        texts.append(output(passed))
        self.assertEqual(passed.returncode, 0, output(passed))
        runs = [json.loads(line) for line in self.messaging_record.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(runs), 1, runs)
        self.assertEqual(runs[0]["input"]["target"]["cloud"], {"profile": "dev-ro"})
        texts.append((self.box.config_home / "probes.log").read_text(encoding="utf-8"))
        for text in texts:
            self.assertNotIn("dev-ro", text)


if __name__ == "__main__":
    unittest.main()
