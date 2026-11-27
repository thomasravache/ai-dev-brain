"""Segredo na inbox pela CLI: `lint --only secret-in-note` lê os itens de texto e de link da inbox e o `inbox list`
avisa e mascara, sem nunca mostrar o valor (SPEC-0112: UT-03, UT-04, UT-05, IT-01).

Cada teste cria o vault com o `brain.py init` real (contexto college) num diretório temporário com HOME,
XDG_CONFIG_HOME e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). Valores falsos, montados por concatenação.

Saídas que os testes conferem (contrato da seção 6):
    lint --only secret-in-note [--json]
        percorre as notas e inbox/*.md, inbox/*.txt, inbox/*.url, inbox/*.webloc; um achado por linha com segredo:
        "AVISO secret-in-note <arquivo>:<linha> — ..." (no JSON, severity "warn" e a linha no path ou no detail);
        nunca o valor. Severidade de hoje: AVISO e exit 0 (Emenda v2).
    capture TEXTO
        o nome do arquivo (e por ele a saída e o log.md) nunca leva um valor de secret_spans; o rótulo fica
        ("Senha do wifi: abc12345" -> ...-senha-do-wifi.md); texto só com segredo -> ...-captura.md (UT-07).
    inbox list [--json]
        item com segredo: a linha do item termina com "(possível segredo)" (depois de " (parado)", se houver) e a
        prévia troca cada valor por "•••"; --json: "secret": true e "preview" já mascarada. Sem segredo: como hoje
        (sem a marca e sem "secret" verdadeiro).
    log.md não ganha nenhum dos valores.
    nome antigo com o valor (Emenda v3, UT-08): o trecho do nome que é o slug de um valor detectado no conteúdo
        aparece como "•••" no lint e no inbox list (texto e JSON); o caminho mascarado é aceito como ITEM por
        `inbox done` e `ingest --move` quando identifica um único item, senão exit 2 "item não encontrado"; ao sair
        da inbox o trecho vira "segredo" (destino, log.md, nota de fonte e saídas, nunca o valor).
"""
import datetime as dt
import json
import re

from brain_support import fn, output, snapshot
from test_inbox_cli import InboxCliTestCase, year

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
        """Severidade de hoje (Emenda v2): secret-in-note é AVISO (warn) e o lint sai com 0."""
        self.assertExit(out, 0)
        if text_lines is None:
            findings = [f for f in json.loads(out.stdout)["findings"] if f["rule"] == "secret-in-note"]
            self.assertEqual({f["severity"] for f in findings} - {"warn"}, set(), findings)
        else:
            hits = [t for t in text_lines if " secret-in-note " in t]
            self.assertFalse([t for t in hits if not t.startswith("AVISO ")], hits)

    def text_hits(self, out, rel, line):
        pattern = re.compile(rf"^AVISO secret-in-note {re.escape(rel)}:{line} — ")
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


class CaptureNameCliTest(InboxSecretsCliTestCase):
    def test_capture_of_a_secret_keeps_the_value_out_of_name_output_and_log(self):
        """SPEC-0112:UT-07"""
        # SPEC-0112:UT-07
        log_before = self.log()
        out = self.box.run("capture", "Senha do wifi: " + WIFI)
        self.assertExit(out, 0)
        self.assertNoValue(output(out), (WIFI,))
        rel = self.rel([t for t in out.stdout.splitlines() if t.strip()][-1])
        self.assertRegex(rel, r"^inbox/\d{4}-\d{2}-\d{2}-\d{6}-senha-do-wifi\.md$")
        names = [p.name for p in (self.box.vault / "inbox").iterdir()]
        self.assertNoValue(" ".join(names), (WIFI,))
        self.assertNoValue(self.log(), (WIFI,))
        self.assertTrue(self.log().startswith(log_before))
        self.assertIn(WIFI, self.read(rel), "o texto da captura continua o que a pessoa escreveu")


class InboxSecretFlowCliTest(InboxSecretsCliTestCase):
    def test_capture_and_txt_item_are_flagged_by_list_and_lint(self):
        """SPEC-0112:IT-01"""
        # SPEC-0112:IT-01
        # o caso real: o segredo no começo da captura (o nome não leva o valor, Emenda v2)
        out = self.box.run("capture", "Senha do wifi: " + WIFI + " para as visitas")
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
                hits = [t for t in text_lines if re.match(rf"^AVISO secret-in-note {re.escape(rel)}:\d+ — ", t)]
                self.assertEqual(len(hits), 1, out.stdout)
        self.assertNoValue(self.log(), (WIFI,))


OLD_VALUE = "qz9" + "vold1"
OLD_STAMP = "2026-01-01-120000"
OLD_NAME = f"{OLD_STAMP}-senha-do-wifi-{OLD_VALUE}.md"
OLD_MASKED = f"inbox/{OLD_STAMP}-senha-do-wifi-{MASK}.md"
OLD_CLEAN = f"{OLD_STAMP}-senha-do-wifi-segredo.md"
OLD_TEXT = "---\ntype: capture\ncreated: 2026-01-01\n---\n\nSenha do wifi: " + OLD_VALUE + "\n"


class OldCaptureNameCliTest(InboxSecretsCliTestCase):
    """Captura antiga (slug de seis palavras) com o valor no nome do arquivo."""

    def setUp(self):
        super().setUp()
        self.old = self.put(f"inbox/{OLD_NAME}", OLD_TEXT, age_days=1)

    def assertNoOld(self, text):
        self.assertNoValue(text, (OLD_VALUE,))

    def test_lint_and_inbox_list_show_the_masked_name(self):
        """SPEC-0112:UT-08"""
        # SPEC-0112:UT-08
        out = self.lint()
        self.assertLintExit(out, out.stdout.splitlines())
        self.assertNoOld(output(out))
        self.assertEqual(len(self.text_hits(out, OLD_MASKED, 6)), 1, out.stdout)

        out = self.lint("--json")
        self.assertLintExit(out)
        self.assertNoOld(output(out))
        self.assertEqual(len(self.json_hits(json.loads(out.stdout)["findings"], OLD_MASKED, 6)), 1, out.stdout)

        out = self.run_in_vault("lint")
        self.assertNotIn("Traceback", output(out))
        self.assertNoOld(output(out))

        out, lines = self.list_lines()
        self.assertNoOld(out.stdout)
        self.assertTrue(any(OLD_MASKED in t and t.rstrip().endswith(FLAG) for t in lines), out.stdout)

        out = self.run_in_vault("inbox", "list", "--json")
        self.assertExit(out, 0)
        self.assertNoOld(out.stdout)
        items = json.loads(out.stdout)["items"]
        self.assertEqual([self.rel(i["path"]) for i in items], [OLD_MASKED], items)
        self.assertIs(items[0].get("secret"), True, items[0])

    def test_inbox_done_takes_the_masked_path_and_cleans_the_name(self):
        """SPEC-0112:UT-08"""
        # SPEC-0112:UT-08
        log_before = self.log()
        out = self.run_in_vault("inbox", "done", OLD_MASKED)
        self.assertExit(out, 0)
        self.assertNoOld(output(out))
        self.assertFalse(self.old.exists(), "o item saiu da inbox")
        dest = self.processed(OLD_CLEAN)
        self.assertTrue((self.box.vault / dest).is_file())
        self.assertNoOld(self.log())
        lines = self.new_log_lines(log_before)
        self.assertTrue(any(OLD_CLEAN in line for line in lines), lines)

    def test_ingest_move_takes_the_masked_path_and_cleans_name_log_and_source_note(self):
        """SPEC-0112:UT-08"""
        # SPEC-0112:UT-08
        log_before = self.log()
        out = self.run_in_vault("ingest", OLD_MASKED, "--move", "--context", "college", "--json")
        self.assertExit(out, 0)
        self.assertNoOld(output(out))
        self.assertFalse(self.old.exists(), "o item saiu da inbox")
        data = json.loads(out.stdout)
        # destino de hoje do ingest --move (SPEC-0021): <files>/<contexto>/<AAAA>/<nome>, com o nome limpo
        self.assertEqual(data["file"], f"college/{year()}/{OLD_CLEAN}")
        self.assertTrue((self.box.files / data["file"]).is_file())
        raw = self.rel(data["raw"])
        self.assertNoOld(raw)
        self.assertNoOld(self.read(raw))
        title = str(self.note(raw).frontmatter.get("title") or "")
        self.assertNoOld(title)
        self.assertIn("segredo", title.lower())
        self.assertNoOld(self.log())
        self.assertTrue(self.log().startswith(log_before))
        moved = [p.name for p in (self.box.files).rglob("*")] + [p.name for p in self.box.vault.rglob("*")]
        self.assertNoOld(" ".join(moved))

    def test_a_masked_path_that_names_no_single_item_exits_2(self):
        """SPEC-0112:UT-08"""
        # SPEC-0112:UT-08
        other = "mm7" + "kp2xa"
        self.put(f"inbox/{OLD_STAMP}-senha-do-wifi-{other}.md", OLD_TEXT.replace(OLD_VALUE, other), age_days=1)
        cases = {"ambíguo": OLD_MASKED, "inexistente": f"inbox/{OLD_STAMP}-senha-da-casa-{MASK}.md"}
        for case, item in cases.items():
            for command in (("inbox", "done", item), ("ingest", item, "--move", "--context", "college")):
                with self.subTest(case=case, command=command[0]):
                    before = self.state()
                    out = self.run_in_vault(*command)
                    self.assertExit(out, 2)
                    self.assertIn("item não encontrado", output(out))
                    self.assertNoValue(output(out), (OLD_VALUE, other))
                    self.assertEqual(self.state(), before, "nada se move e o log não muda")

    def state(self):
        files = {k: v[0] for k, v in snapshot(self.box.files).items()} if self.box.files.exists() else {}
        return {k: v[0] for k, v in snapshot(self.box.vault).items()}, files


# Emenda v4: valor longo cortado no nome antigo (slugify cortava em SLUG_MAX = 60) e limites do slug
LONG_VALUE = "".join(chr(97 + (i * 7) % 26) + str(i % 10) for i in range(35))  # 70 caracteres falsos
LONG_SLUG = ("token-" + LONG_VALUE)[:60]
LONG_NAME = f"{OLD_STAMP}-{LONG_SLUG}.md"
LONG_MASKED = f"inbox/{OLD_STAMP}-token-{MASK}.md"
LONG_CLEAN = f"{OLD_STAMP}-token-segredo.md"
PIN_DATE_NAME = f"{OLD_STAMP}-pin-2026.md"
PIN_DATE_MASKED = f"inbox/{OLD_STAMP}-pin-{MASK}.md"
PIN_DATE_CLEAN = f"{OLD_STAMP}-pin-segredo.md"
HOUR_STAMP = "2026-01-02-120000"
HOUR_NAME = f"{HOUR_STAMP}-pin.md"  # o nome que capture_name dá a "PIN 120000" às 12:00:00


def capture_text(body, created="2026-01-01"):
    return f"---\ntype: capture\ncreated: {created}\n---\n\n{body}\n"


class OldNameLimitsCliTest(InboxSecretsCliTestCase):
    def pieces(self):
        return {LONG_VALUE[i:i + 4] for i in range(len(LONG_VALUE) - 3)}

    def test_a_long_value_cut_in_the_old_name_never_shows_a_piece(self):
        """SPEC-0112:UT-08 — nome antigo cortado em 60 caracteres do slug"""
        # SPEC-0112:UT-08
        self.assertEqual(len(LONG_SLUG), 60)
        self.put(f"inbox/{LONG_NAME}", capture_text("token: " + LONG_VALUE), age_days=1)
        runs = {"lint": self.lint(), "lint --json": self.lint("--json"),
                "inbox list": self.run_in_vault("inbox", "list"),
                "inbox list --json": self.run_in_vault("inbox", "list", "--json")}
        for name, out in runs.items():
            with self.subTest(command=name):
                self.assertNotIn("Traceback", output(out))
                text = output(out)
                shown = sorted(p for p in self.pieces() if p in text)
                self.assertEqual(shown, [], f"pedaços do valor na saída: {text}")
        self.assertIn(LONG_MASKED, runs["inbox list"].stdout)
        items = json.loads(runs["inbox list --json"].stdout)["items"]
        self.assertEqual([self.rel(i["path"]) for i in items], [LONG_MASKED], items)

        out = self.run_in_vault("inbox", "done", LONG_MASKED)
        self.assertExit(out, 0)
        self.assertEqual(sorted(p for p in self.pieces() if p in output(out) + self.log()), [])
        self.processed(LONG_CLEAN)

    def test_pin_equal_to_the_year_keeps_the_date(self):
        """SPEC-0112:UT-08 — dígitos da data nunca são trocados"""
        # SPEC-0112:UT-08
        self.put(f"inbox/{PIN_DATE_NAME}", capture_text("PIN 2026"), age_days=1)
        out, lines = self.list_lines()
        self.assertTrue(any(PIN_DATE_MASKED in t and t.rstrip().endswith(FLAG) for t in lines), out.stdout)
        items = self.inbox_items()
        self.assertEqual([self.rel(i["path"]) for i in items], [PIN_DATE_MASKED], items)
        out = self.lint()
        self.assertLintExit(out, out.stdout.splitlines())
        self.assertEqual(len(self.text_hits(out, PIN_DATE_MASKED, 6)), 1, out.stdout)

        out = self.run_in_vault("inbox", "done", PIN_DATE_MASKED)
        self.assertExit(out, 0)
        self.processed(PIN_DATE_CLEAN)

    def test_pin_equal_to_the_hour_keeps_the_hour(self):
        """SPEC-0112:UT-08 — dígitos da hora nunca são trocados"""
        # SPEC-0112:UT-08
        name = fn("capture_name", "SPEC-0021")("PIN 120000", (), lambda: dt.datetime(2026, 1, 2, 12, 0, 0))
        self.assertEqual(name, HOUR_NAME)
        self.put(f"inbox/{name}", capture_text("PIN 120000", "2026-01-02"), age_days=1)
        rel = f"inbox/{name}"
        out, lines = self.list_lines()
        self.assertTrue(any(rel in t and t.rstrip().endswith(FLAG) for t in lines), out.stdout)
        self.assertEqual([self.rel(i["path"]) for i in self.inbox_items()], [rel])
        out = self.lint()
        self.assertLintExit(out, out.stdout.splitlines())
        self.assertEqual(len(self.text_hits(out, rel, 6)), 1, out.stdout)
        out = self.run_in_vault("inbox", "done", rel)
        self.assertExit(out, 0)
        self.processed(name)
