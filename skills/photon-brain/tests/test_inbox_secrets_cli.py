"""Segredo na inbox pela CLI: `lint --only secret-in-note` lê os itens de texto e de link da inbox e o `inbox list`
avisa e mascara, sem nunca mostrar o valor (SPEC-0112: UT-03, UT-04, UT-05, IT-01).

Cada teste cria o vault com o `brain.py init` real (contexto college) num diretório temporário com HOME,
XDG_CONFIG_HOME e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). Valores falsos, montados por concatenação.

Saídas que os testes conferem (contrato da seção 6):
    lint --only secret-in-note [--json]
        percorre as notas e inbox/*.md, inbox/*.txt, inbox/*.url, inbox/*.webloc; um achado por linha com segredo:
        "<ERRO|AVISO> secret-in-note <arquivo>:<linha> — ..." (no JSON, a linha no path ou no detail); nunca o valor.
        O rótulo (ERRO/AVISO) e o exit seguem a regra de hoje: exit 1 se houver ERRO, 0 se não (os testes aceitam
        os dois, coerentes entre si — ver o relatório do G1).
    inbox list [--json]
        item com segredo: a linha do item termina com "(possível segredo)" (depois de " (parado)", se houver) e a
        prévia troca cada valor por "•••"; --json: "secret": true e "preview" já mascarada. Sem segredo: como hoje
        (sem a marca e sem "secret" verdadeiro).
    log.md não ganha nenhum dos valores.
"""
import json
import re

from brain_support import output
from test_inbox_cli import InboxCliTestCase

MASK = "•••"
FLAG = "(possível segredo)"
WIFI = "abc12345"
URL_TOKEN = "abcdef123456"
PIN = "4821"
VALUES = (WIFI, URL_TOKEN, PIN)
TXT = "inbox/2026-01-01-wifi.txt"
LINK = "inbox/link.url"
NOTE = "inbox/2026-01-02-cadeado.md"
PLAIN = "inbox/ideia.md"
URL = "https://exemplo.test/wifi?token=" + URL_TOKEN
NOTE_TEXT = "---\ntype: capture\ncreated: 2026-01-02\n---\n\nLembrete do cadeado\nPIN " + PIN + "\n"
# item -> (linha do segredo no arquivo, prévia mascarada esperada)
EXPECTED = {
    TXT: (1, "Senha do wifi: " + MASK),
    LINK: (2, "https://exemplo.test/wifi?token=" + MASK),
    NOTE: (7, "Lembrete do cadeado PIN " + MASK),
}


class InboxSecretsCliTestCase(InboxCliTestCase):
    def setUp(self):
        super().setUp()
        self.make_vault()

    def fill_inbox(self):
        self.put(TXT, "Senha do wifi: " + WIFI + "\n", age_days=4)
        self.put(LINK, "[InternetShortcut]\nURL=" + URL + "\n", age_days=3)
        self.put(NOTE, NOTE_TEXT, age_days=2)
        self.put(PLAIN, "Ideia sobre grafos de conhecimento\n", age_days=1)

    def assertNoValue(self, text, values=VALUES):
        for value in values:
            self.assertNotRegex(text, rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", "valor exposto")

    def lint(self, *extra):
        return self.run_in_vault("lint", "--only", "secret-in-note", *extra)

    def assertLintExit(self, out, text_lines=None):
        """Exit coerente com os rótulos: 1 com algum ERRO, 0 só com AVISO (regra de hoje do lint)."""
        self.assertNotIn("Traceback", output(out))
        if text_lines is None:
            findings = json.loads(out.stdout)["findings"]
            has_error = any(f["severity"] == "error" for f in findings)
        else:
            has_error = any(line.startswith("ERRO ") for line in text_lines)
        self.assertEqual(out.returncode, 1 if has_error else 0, output(out))

    def text_hits(self, out, rel, line):
        pattern = re.compile(rf"^(ERRO|AVISO) secret-in-note {re.escape(rel)}:{line} — ")
        return [t for t in out.stdout.splitlines() if pattern.match(t)]

    def json_hits(self, findings, rel, line):
        return [f for f in findings if f["rule"] == "secret-in-note" and f["path"] in (rel, f"{rel}:{line}")
                and re.search(rf"(?<!\d){line}(?!\d)", f"{f['path']} {f['detail']}")]

    def list_lines(self):
        out = self.run_in_vault("inbox", "list")
        self.assertExit(out, 0)
        return out, out.stdout.splitlines()


class InboxSecretLintCliTest(InboxSecretsCliTestCase):
    def test_lint_flags_txt_link_and_md_items_with_file_and_line(self):
        """SPEC-0112:UT-03"""
        # SPEC-0112:UT-03
        self.fill_inbox()
        out = self.lint()
        lines = out.stdout.splitlines()
        self.assertLintExit(out, lines)
        for rel, (line, _) in EXPECTED.items():
            with self.subTest(item=rel):
                self.assertEqual(len(self.text_hits(out, rel, line)), 1, out.stdout)
        self.assertFalse([t for t in lines if PLAIN in t], "item sem segredo não é acusado")

        out = self.lint("--json")
        self.assertLintExit(out)
        findings = json.loads(out.stdout)["findings"]
        for rel, (line, _) in EXPECTED.items():
            with self.subTest(item=rel, json=True):
                self.assertEqual(len(self.json_hits(findings, rel, line)), 1, findings)
        self.assertEqual(len([f for f in findings if f["rule"] == "secret-in-note"]), 3, findings)

    def test_lint_reads_webloc_items(self):
        """SPEC-0112:UT-03 — o outro formato de link"""
        # SPEC-0112:UT-03
        rel = "inbox/wifi.webloc"
        self.put(rel, '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">\n<dict>\n<key>URL</key>\n'
                      "<string>https://exemplo.test/x?token=" + URL_TOKEN + "</string>\n</dict>\n</plist>\n")
        out = self.lint()
        self.assertLintExit(out, out.stdout.splitlines())
        self.assertEqual(len(self.text_hits(out, rel, 5)), 1, out.stdout)
        self.assertNoValue(output(out), (URL_TOKEN,))

    def test_unreadable_item_does_not_break_the_lint(self):
        """SPEC-0112:UT-03 — codificação inválida é pulada (seção 5)"""
        # SPEC-0112:UT-03
        self.put(TXT, "Senha do wifi: " + WIFI + "\n")
        self.put("inbox/ruim.txt", b"\xff\xfe\x00senha\x9c\xe0 de \xc3\x28 lixo\n")
        out = self.lint()
        self.assertLintExit(out, out.stdout.splitlines())
        self.assertEqual(len(self.text_hits(out, TXT, 1)), 1, out.stdout)


class InboxSecretNoValueCliTest(InboxSecretsCliTestCase):
    def test_no_value_in_lint_inbox_list_nor_log(self):
        """SPEC-0112:UT-04"""
        # SPEC-0112:UT-04
        self.fill_inbox()
        log_before = self.log()
        runs = {
            "lint": self.run_in_vault("lint"),
            "lint --json": self.run_in_vault("lint", "--json"),
            "inbox list": self.run_in_vault("inbox", "list"),
            "inbox list --json": self.run_in_vault("inbox", "list", "--json"),
        }
        for name, out in runs.items():
            with self.subTest(command=name):
                self.assertNotIn("Traceback", output(out))
                self.assertNoValue(output(out))
        lint_out = runs["lint --json"]
        self.assertEqual(len([f for f in json.loads(lint_out.stdout)["findings"]
                              if f["rule"] == "secret-in-note"]), 3, "o lint inteiro também lê a inbox")
        self.assertNoValue(self.log())
        self.assertTrue(self.log().startswith(log_before))


class InboxSecretListCliTest(InboxSecretsCliTestCase):
    def test_list_flags_and_masks_secret_items(self):
        """SPEC-0112:UT-05"""
        # SPEC-0112:UT-05
        self.fill_inbox()
        out, lines = self.list_lines()
        self.assertNoValue(out.stdout)
        for rel, (_, preview) in EXPECTED.items():
            with self.subTest(item=rel):
                index = next((i for i, t in enumerate(lines) if rel in t), None)
                self.assertIsNotNone(index, out.stdout)
                self.assertTrue(lines[index].rstrip().endswith(FLAG), lines[index])
                self.assertEqual(lines[index + 1].strip(), preview)
        plain = next(i for i, t in enumerate(lines) if PLAIN in t)
        self.assertNotIn(FLAG, lines[plain])
        self.assertEqual(lines[plain + 1].strip(), "Ideia sobre grafos de conhecimento")

    def test_json_has_secret_true_and_masked_preview(self):
        """SPEC-0112:UT-05"""
        # SPEC-0112:UT-05
        self.fill_inbox()
        items = {self.rel(i["path"]): i for i in self.inbox_items()}
        for rel, (_, preview) in EXPECTED.items():
            with self.subTest(item=rel):
                self.assertIs(items[rel].get("secret"), True, items[rel])
                self.assertEqual(items[rel]["preview"], preview)
        plain = items[PLAIN]
        self.assertFalse(plain.get("secret"), plain)
        self.assertEqual(plain["preview"], "Ideia sobre grafos de conhecimento")
        self.assertTrue({"path", "kind", "size", "age_days", "stale", "preview"} <= set(plain), plain)


class InboxSecretFlowCliTest(InboxSecretsCliTestCase):
    def test_capture_and_txt_item_are_flagged_by_list_and_lint(self):
        """SPEC-0112:IT-01"""
        # SPEC-0112:IT-01
        # o valor fica depois das seis primeiras palavras: o nome da captura usa só elas (ver o relatório do G1)
        out = self.box.run("capture", "Lembrete para as visitas de casa: Senha do wifi: " + WIFI)
        self.assertExit(out, 0)
        self.assertNoValue(output(out), (WIFI,))
        captured = self.rel([t for t in out.stdout.splitlines() if t.strip()][-1])
        self.put(TXT, "Senha do wifi: " + WIFI + "\n")

        items = {self.rel(i["path"]): i for i in self.inbox_items()}
        for rel in (captured, TXT):
            with self.subTest(item=rel, command="inbox list --json"):
                self.assertIs(items[rel].get("secret"), True, items[rel])
                self.assertIn(MASK, items[rel]["preview"])
        out, lines = self.list_lines()
        self.assertNoValue(out.stdout, (WIFI,))
        for rel in (captured, TXT):
            with self.subTest(item=rel, command="inbox list"):
                self.assertTrue(any(rel in t and t.rstrip().endswith(FLAG) for t in lines), out.stdout)

        out = self.run_in_vault("lint")
        text_lines = out.stdout.splitlines()
        self.assertLintExit(out, text_lines)
        self.assertNoValue(output(out), (WIFI,))
        for rel in (captured, TXT):
            with self.subTest(item=rel, command="lint"):
                hits = [t for t in text_lines if re.match(rf"^(ERRO|AVISO) secret-in-note {re.escape(rel)}:\d+ — ", t)]
                self.assertEqual(len(hits), 1, out.stdout)
        self.assertNoValue(self.log(), (WIFI,))
