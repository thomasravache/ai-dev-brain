"""Integração pela CLI: secret-ref, ingest opaco, filtros, índice, exportação, lint e doctor com itens confidenciais
(SPEC-0050: IT-01 a IT-07; e as partes de UT-05 e UT-06 que só a CLI mostra: o texto do lint e o finding config).

Cada teste cria o vault com o `brain.py init` real (contexto college) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). Processadores são scripts Python escritos pelo teste: o do
IT-02/IT-03 grava um arquivo-marcador quando roda. Mensagens de erro podem ir para stdout ou stderr.

Saídas que os testes conferem (contrato da seção 6):
    new-note --type secret-ref --title X --vault-ref REF [--json]  -> frontmatter type: secret-ref,
        confidential: true e vault_ref: REF; sem --vault-ref, REF fora de "<esquema>://<caminho>" ou --vault-ref
        com outro tipo -> exit 2 e nada criado. new-note --type T --confidential -> confidential: true.
    ingest ARQ --confidential [--move] [--json] -> {"raw", "file", "url": null, "confidential": true}; nota de fonte
        com confidential: true, size (bytes), sha256 e "_(confidential: not extracted)_"; processador não roda;
        URL, --text-file, --kind ou --timestamps com --confidential -> exit 2 e nada criado.
    search | related | context | links [--include-confidential] --json -> "confidential_omitted": N (notas distintas)
        related --note / links numa nota confidencial sem a opção -> exit 2.
    index -> o MOC (região notes) e index.md (região recent) não listam nota confidencial.
    export-notebooklm C --out PASTA --json -> nota confidencial fora de "notes" e do pacote; "confidential_omitted".
    lint [--json] -> AVISO secret-in-note / personal-data com caminho, linha e tipo, sem o valor; no texto
        "<caminho>:<linha>"; nota confidencial sem achado nem orphan. lint.personal_data e
        lint.personal_data_patterns no brain-config.yml; padrão inválido ou perigoso -> finding config.
    doctor -> "OK confidential — N notas confidenciais", sem título nem caminho delas.
"""
import hashlib
import json
import re
import shlex
import sys

from brain_support import doctor_lines, fn, output, snapshot
from test_store_cli import StoreCliTestCase, region

PY = shlex.quote(sys.executable)
NOT_EXTRACTED = "_(confidential: not extracted)_"
PDF_SECRET = "CONTEUDO-SIGILOSO-SPEC0050"
PDF_BYTES = b"%PDF-1.4 " + PDF_SECRET.encode() + b" fim"
EXTRACTED = "texto extraído do PDF"
# processador falso: grava o texto e, se receber, um marcador (prova de que rodou)
FAKE_TEXT = """import sys
from pathlib import Path
Path(sys.argv[2]).write_text("texto extraído do PDF\\n", encoding="utf-8")
if len(sys.argv) > 3:
    Path(sys.argv[3]).write_text("rodou", encoding="utf-8")
"""
LABELED = "senha: " + "hunter22"
CPF = "CPF: 123.456.789-09"
SHA = re.compile(r"\b[0-9a-f]{64}\b")


def frontmatter_of(text):
    data, _, _ = fn("read_frontmatter", "SPEC-0018")(text)
    return data


def note_text(title, body, confidential=False, context="college", extra=""):
    lines = ["---", "type: note", f"title: {title}"] + ([f"context: {context}"] if context else [])
    lines += ["created: 2026-10-01", "tags: []"]
    if confidential:
        lines.append("confidential: true")
    return "\n".join(lines) + f"\n{extra}---\n\n# {title}\n\n{body}\n\n## Relations\n"


class ConfidentialCliTestCase(StoreCliTestCase):
    def setUp(self):
        super().setUp()
        self.make_vault()

    def state(self):
        """Conteúdo de cada arquivo do vault e da pasta files (nada criado = estado igual)."""
        return ({k: v[0] for k, v in snapshot(self.box.vault).items()},
                {k: v[0] for k, v in snapshot(self.box.files).items()} if self.box.files.exists() else {})

    def assertRefused(self, *args):
        before = self.state()
        out = self.box.run(*args)
        self.assertExit(out, 2)
        self.assertEqual(self.state(), before, f"nada criado: {args}")
        return out


class SecretRefCliTest(ConfidentialCliTestCase):
    def test_secret_ref_and_confidential_note_and_invalid_refs(self):
        """SPEC-0050:IT-01 SPEC-0050:UT-01"""
        data = self.json_of("new-note", "--type", "secret-ref", "--title", "Banco",
                            "--vault-ref", "keepass://Pessoal/Banco")
        rel = self.rel(data["path"])
        text = self.read(rel)
        fm = frontmatter_of(text)
        self.assertEqual(fm.get("type"), "secret-ref", text)
        self.assertRegex(text, r"(?m)^confidential: true\s*$")
        self.assertEqual(fm.get("vault_ref"), "keepass://Pessoal/Banco", text)
        self.assertTrue(fn("is_confidential", "SPEC-0050")(self.note(rel)))

        out = self.box.run("new-note", "--type", "note", "--title", "Doc", "--confidential", "--context", "college")
        self.assertExit(out, 0)
        doc = self.rel(out.stdout.strip().splitlines()[-1])
        doc_text = self.read(doc)
        self.assertEqual(frontmatter_of(doc_text).get("type"), "note", doc_text)
        self.assertRegex(doc_text, r"(?m)^confidential: true\s*$")
        self.assertNotIn("vault_ref", doc_text)

        self.assertRefused("new-note", "--type", "secret-ref", "--title", "Sem ref")
        self.assertRefused("new-note", "--type", "secret-ref", "--title", "Ref ruim", "--vault-ref", "banco")
        self.assertRefused("new-note", "--type", "note", "--title", "Outro tipo", "--vault-ref", "keepass://x/y")


class ConfidentialIngestCliTest(ConfidentialCliTestCase):
    def setUp(self):
        super().setUp()
        self.marker = self.box.root / "markers" / "rodou.txt"
        self.marker.parent.mkdir()
        fake = self.box.root / "fakes" / "text.py"
        fake.parent.mkdir()
        fake.write_text(FAKE_TEXT, encoding="utf-8")
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = self.box.vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        command = f"{PY} {shlex.quote(str(fake))} {{input}} {{output}} {shlex.quote(str(self.marker))}"
        data["processors"] = {"pdf": {"command": command}}
        shared.write_text(dump(data), encoding="utf-8")

    def assertOpaque(self, data, expected_bytes):
        self.assertEqual(data.get("confidential"), True, data)
        self.assertIsNone(data.get("url"), data)
        rel, file_rel = self.rel(data["raw"]), data["file"]
        stored = self.box.files / file_rel
        self.assertTrue(stored.is_file(), f"arquivo em files/: {file_rel}")
        self.assertEqual(stored.read_bytes(), expected_bytes)
        text = self.read(rel)
        fm = frontmatter_of(text)
        self.assertRegex(text, r"(?m)^confidential: true\s*$")
        self.assertEqual(str(fm.get("size")), str(len(expected_bytes)), text)
        self.assertEqual(str(fm.get("sha256")), hashlib.sha256(expected_bytes).hexdigest(), text)
        self.assertIn(NOT_EXTRACTED, text)
        self.assertNotIn(EXTRACTED, text)
        self.assertNotIn(PDF_SECRET, text)
        self.assertFalse(self.marker.exists(), "o processador não pode rodar num documento confidencial")
        return rel, file_rel

    def test_confidential_pdf_is_stored_without_extraction(self):
        """SPEC-0050:IT-02"""
        pdf = self.source("doc.pdf", PDF_BYTES)
        data = self.json_of("ingest", pdf, "--confidential", "--context", "college")
        self.assertEqual(set(data), {"raw", "file", "url", "confidential"}, data)
        self.assertOpaque(data, PDF_BYTES)

    def test_extraction_options_are_refused_with_confidential(self):
        """SPEC-0050:IT-02"""
        pdf = self.source("doc.pdf", PDF_BYTES)
        text = self.source("texto.txt", "texto")
        self.json_of("ingest", pdf, "--confidential")  # a opção existe: o resto é recusa, não "argumento inválido"
        for extra in (("https://exemplo.com/doc.pdf", "--confidential"),
                      (pdf, "--confidential", "--text-file", text),
                      (pdf, "--confidential", "--kind", "pdf"),
                      (pdf, "--confidential", "--timestamps")):
            with self.subTest(args=extra):
                self.assertRefused("ingest", *extra)
        self.assertFalse(self.marker.exists())

    def test_processor_never_runs_and_log_only_cites_paths(self):
        """SPEC-0050:IT-03"""
        log_before = self.log()
        pdf = self.source("rg.pdf", PDF_BYTES)
        copied = self.json_of("ingest", pdf, "--confidential", "--context", "college")
        rel, file_rel = self.assertOpaque(copied, PDF_BYTES)

        inbox_pdf = self.box.vault / "inbox" / "contrato.pdf"
        inbox_pdf.write_bytes(PDF_BYTES)
        moved = json.loads(self.box.run("ingest", "inbox/contrato.pdf", "--confidential", "--move", "--json",
                                        cwd=self.box.vault).stdout or "{}")
        self.assertTrue(moved, "ingest --confidential --move --json")
        moved_rel, moved_file = self.assertOpaque(moved, PDF_BYTES)
        self.assertFalse(inbox_pdf.exists(), "--move tira o item da inbox")

        lines = self.new_log_lines(log_before)
        joined = "\n".join(lines)
        for path in (rel, file_rel, moved_rel, moved_file):
            self.assertIn(path, joined)
        for leaked in (PDF_SECRET, EXTRACTED, "extraído", "extração", hashlib.sha256(PDF_BYTES).hexdigest()):
            self.assertNotIn(leaked, joined)
        self.assertFalse(SHA.search(joined), joined)
        self.assertFalse(self.marker.exists())


COMUM = "projects/college/Conta comum.md"
SIGILOSA = "projects/college/Conta sigilosa.md"


class ConfidentialQueryCliTest(ConfidentialCliTestCase):
    def setUp(self):
        super().setUp()
        self.write(COMUM, note_text("Conta comum", "Banco do bairro, abrir conta. Ver [[Conta sigilosa]]."))
        self.write(SIGILOSA, note_text("Conta sigilosa", "Banco e agência da conta. Ver [[Conta comum]].", True))

    def payload(self, *args):
        return self.json_of(*args)

    def assertHidden(self, data, omitted=1):
        """A nota confidencial não está em nenhuma lista da saída (o texto das notas comuns pode citá-la)."""
        listed = [r["path"] for r in data.get("results", [])]
        listed += [n["path"] for n in data.get("notes", []) + data.get("omitted", [])]
        listed += [o["path"] for o in data.get("outgoing", [])] + list(data.get("backlinks", []))
        targets = [o["target"] for o in data.get("outgoing", [])] + list(data.get("broken", []))
        targets += [b["target"] for b in data.get("broken", []) if isinstance(b, dict)]
        self.assertNotIn(SIGILOSA, listed, data)
        self.assertNotIn("Conta sigilosa", [t for t in targets if isinstance(t, str)], data)
        self.assertEqual(data.get("confidential_omitted"), omitted, data)

    def test_search_related_context_and_links_hide_the_confidential_note(self):
        """SPEC-0050:IT-04"""
        hidden = (("search", "banco"), ("related", "--text", "banco"), ("context", "banco"),
                  ("links", "Conta comum"))
        for args in hidden:
            with self.subTest(args=args):
                self.assertHidden(self.payload(*args))
        self.assertNotIn(SIGILOSA, output(self.box.run("search", "banco")))

        shown = self.payload("search", "banco", "--include-confidential")
        self.assertIn(SIGILOSA, [r["path"] for r in shown["results"]])
        shown = self.payload("related", "--text", "banco", "--include-confidential")
        self.assertIn(SIGILOSA, [r["path"] for r in shown["results"]])
        shown = self.payload("context", "banco", "--include-confidential")
        self.assertIn(SIGILOSA, [n["path"] for n in shown["notes"]])
        shown = self.payload("links", "Conta comum", "--include-confidential")
        self.assertIn(SIGILOSA, [o["path"] for o in shown["outgoing"]])
        self.assertIn(SIGILOSA, shown["backlinks"])

        for args in (("related", "--note", "Conta sigilosa"), ("links", "Conta sigilosa")):
            with self.subTest(args=args):
                out = self.box.run(*args)
                self.assertExit(out, 2)
                self.assertIn("confidencial", output(out))
                self.assertIn("--include-confidential", output(out))
        self.assertExit(self.box.run("related", "--note", "Conta sigilosa", "--include-confidential"), 0)
        self.assertExit(self.box.run("links", "Conta sigilosa", "--include-confidential"), 0)


class ConfidentialIndexExportCliTest(ConfidentialCliTestCase):
    def test_moc_recent_and_export_leave_the_confidential_note_out(self):
        """SPEC-0050:IT-05"""
        self.write("projects/college/Aula comum.md", note_text("Aula comum", "Limites e derivadas."))
        self.write("projects/college/Aula sigilosa.md",
                   note_text("Aula sigilosa", f"Conteúdo {PDF_SECRET} da aula.", True))
        moc = self.box.vault / "mocs" / "college.md"
        with open(moc, "a", encoding="utf-8") as handle:
            handle.write("\n- [[Aula comum]]\n- [[Aula sigilosa]]\n")

        self.assertExit(self.box.run("index", "--context", "college"), 0)
        notes_region = region(self.read("mocs/college.md"), "notes")
        self.assertIn("Aula comum", notes_region)
        self.assertNotIn("Aula sigilosa", notes_region)
        recent = region(self.read("index.md"), "recent")
        self.assertIn("Aula comum", recent)
        self.assertNotIn("Aula sigilosa", recent)

        folder = self.box.root / "export"
        out = self.box.run("export-notebooklm", "college", "--out", folder, "--json", "--combined")
        self.assertExit(out, 0)
        data = json.loads(out.stdout)
        paths = [item["path"] for item in data["notes"]]
        self.assertIn("projects/college/Aula comum.md", paths)
        self.assertNotIn("projects/college/Aula sigilosa.md", paths)
        self.assertEqual(data.get("confidential_omitted"), 1, data)
        for path in folder.rglob("*"):
            if path.is_file():
                self.assertNotIn(PDF_SECRET, path.read_text(encoding="utf-8"), path.name)


class ConfidentialLintCliTest(ConfidentialCliTestCase):
    def setUp(self):
        super().setUp()
        body = f"Acesso do banco.\n{LABELED}\n{CPF}"
        self.comum_rel = "projects/college/Acessos.md"
        text = note_text("Acessos", body + "\nVer [[Doc]].")
        self.write(self.comum_rel, text)
        self.write("projects/college/Doc.md", note_text("Doc", "Ver [[Acessos]]."))
        self.write("projects/college/Sigilo.md", note_text("Sigilo", body, True))
        lines = text.splitlines()
        self.secret_line, self.cpf_line = lines.index(LABELED) + 1, lines.index(CPF) + 1

    def assertNoValue(self, text):
        for value in ("hunter22", "123.456.789-09", "12345678909"):
            self.assertNotIn(value, text)

    def test_lint_warns_on_the_common_note_without_printing_the_value(self):
        """SPEC-0050:IT-06 SPEC-0050:UT-05"""
        out = self.box.run("lint", "--json")
        self.assertExit(out, 0)
        self.assertNoValue(output(out))
        findings = json.loads(out.stdout)["findings"]
        mine = [f for f in findings if f["rule"] in ("secret-in-note", "personal-data")]
        self.assertEqual(sorted(f["rule"] for f in mine), ["personal-data", "secret-in-note"], findings)
        for f in mine:
            line = self.secret_line if f["rule"] == "secret-in-note" else self.cpf_line
            kind = "senha rotulada" if f["rule"] == "secret-in-note" else "cpf"
            with self.subTest(rule=f["rule"]):
                self.assertEqual(f["severity"], "warn")
                self.assertTrue(f["path"] in (self.comum_rel, f"{self.comum_rel}:{line}"), f)
                self.assertRegex(f"{f['path']} {f['detail']}", rf"(?<!\d){line}(?!\d)")
                self.assertIn(kind, f["detail"].lower())
        sigilo = [f for f in findings if "Sigilo" in f["path"]]
        self.assertEqual(sigilo, [], "nota confidencial: sem secret-in-note, personal-data nem orphan")

        out = self.box.run("lint")
        self.assertExit(out, 0)
        self.assertNoValue(output(out))
        text_lines = out.stdout.splitlines()
        for rule, line in (("secret-in-note", self.secret_line), ("personal-data", self.cpf_line)):
            with self.subTest(rule=rule):
                hits = [t for t in text_lines if f" {rule} " in t]
                self.assertEqual(len(hits), 1, out.stdout)
                self.assertTrue(hits[0].startswith("AVISO "), hits[0])
                self.assertIn(f"{self.comum_rel}:{line}", hits[0])
        self.assertNotIn("Sigilo", out.stdout)

    def test_configured_detectors_and_dangerous_patterns(self):
        """SPEC-0050:UT-06"""
        shared = self.box.vault / "brain-config.yml"
        with open(shared, "a", encoding="utf-8") as handle:
            handle.write("lint:\n"
                         "  personal_data: [cpf]\n"
                         "  personal_data_patterns:\n"
                         "    nif: '\\bNIF:\\s*\\d{9}\\b'\n"
                         "    ruim: '(abc'\n"
                         "    lento: '(a+)+$'\n")
        self.write("projects/college/Documentos.md",
                   note_text("Documentos", "CNPJ 11.222.333/0001-81\nNIF: 123456789\nVer [[Doc]] e [[Inexiste]]."))
        out = self.box.run("lint", "--json")
        findings = json.loads(out.stdout)["findings"]
        config = [f for f in findings if f["rule"] == "config"]
        self.assertEqual(len(config), 2, findings)
        joined = json.dumps(config, ensure_ascii=False)
        self.assertIn("ruim", joined)
        self.assertIn("lento", joined)
        personal = [f["detail"].lower() for f in findings if f["rule"] == "personal-data"]
        found = sorted("nif" if "nif" in d else "cpf" if "cpf" in d else d for d in personal)
        self.assertEqual(found, ["cpf", "nif"], personal)  # cpf da nota Acessos e o padrão extra; cnpj desligado
        self.assertTrue(any(f["rule"] == "broken-link" for f in findings), "as outras regras rodam")
        self.assertNotIn("123456789", output(out))


class ConfidentialDoctorCliTest(ConfidentialCliTestCase):
    def test_doctor_counts_confidential_notes_only(self):
        """SPEC-0050:IT-07"""
        self.write("projects/college/Cofre Alfa.md", note_text("Cofre Alfa", "a", True))
        self.write("resources/Cofre Beta.md", note_text("Cofre Beta", "b", True, context=None))
        self.write("projects/college/Comum.md", note_text("Comum", "c"))
        out = self.box.run("doctor")
        rows = doctor_lines(out.stdout)
        self.assertIn(("OK", "confidential", "2 notas confidenciais"), rows, out.stdout)
        for leaked in ("Cofre Alfa", "Cofre Beta", "Cofre"):
            self.assertNotIn(leaked, output(out))
