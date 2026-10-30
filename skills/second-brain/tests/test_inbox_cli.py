"""Integração pela CLI: capture, inbox list, ingest --move, inbox done e a inbox entre duas máquinas
(SPEC-0021: IT-01 a IT-05).

Cada teste cria o vault com o `brain.py init` real (SPEC-0017) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox); a pasta `files` é <tmp>/Drive/Vault-files. Os comandos que
recebem um item da inbox rodam com o diretório atual no vault e o item como "inbox/<nome>" (o caminho que o
`inbox list` mostra), o que vale tanto para caminho relativo ao vault quanto ao diretório atual. Idade = mtime
do arquivo (os.utime). Mensagens de erro podem ir para stdout ou stderr.

Saídas que os testes conferem (contrato da seção 6):
    capture TEXTO [--context C]
        cria inbox/AAAA-MM-DD-HHMMSS-<slug>.md com frontmatter type: capture, created, context (quando dado) e o
        TEXTO; imprime o caminho (relativo ao vault ou absoluto); log.md ganha uma linha "- ... capture <caminho>".
        TEXTO vazio -> exit 2, nada escrito.
    inbox list [--json]
        --json: {"items": [{"path", "kind", "size", "age_days", "stale", "preview"}, ...]} do mais antigo para o
        mais novo; path relativo ao vault com "/" (absoluto aceito); stale = age_days > inbox_stale_days (padrão
        7, chave de primeiro nível do brain-config.yml, visível em config --json); preview vazio/null para item
        sem texto (file, syncing). Inbox vazia (sem --json) -> "Inbox vazia", exit 0.
    ingest ITEM --move [--context C] --json
        como o ingest da SPEC-0019 ({"raw", "file", "url"}), mas o arquivo sai da inbox para
        <files>/<contexto>/<AAAA>/<nome>; fonte fora da inbox -> exit 2 "--move só vale para itens da inbox",
        nada muda. Sem --move, o item da inbox é copiado e fica (compatibilidade, seção 8).
    inbox done ITEM [--note CAMINHO]
        text/link -> raw/processed/<AAAA-MM do dia>/<nome>; log "- ... inbox-done <ITEM> → <destino> [nota: ...]"
        file -> exit 2 "arquivo: use ingest --move"; syncing -> exit 2 "ainda sincronizando";
        fora da inbox ou inexistente -> exit 2. Em todo erro o item fica onde estava.
"""
import datetime as dt
import json
import os
import re
import time
import unittest
from pathlib import Path

from brain_support import fn, output, snapshot
from test_cli import CliTestCase

COLLEGE = ("--context", "college=projects/college:College")
CAPTURE_NAME = re.compile(r"^inbox/(\d{4}-\d{2}-\d{2})-\d{6}-ideia-sobre-grafos\.md$")
DAY = 86400


def year():
    return str(dt.date.today().year)


def month():
    return dt.date.today().strftime("%Y-%m")


def region(text, name):
    m = re.search(rf"<!-- brain:begin {name} -->(.*?)<!-- brain:end {name} -->", text, re.DOTALL)
    if not m:
        raise AssertionError(f"região {name} ausente:\n{text}")
    return m.group(1)


class InboxCliTestCase(CliTestCase):
    def make_vault(self):
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(*COLLEGE), 0)

    def put(self, rel, data, age_days=None, base=None):
        path = (base or self.box.vault) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        if age_days is not None:
            stamp = time.time() - age_days * DAY
            os.utime(path, (stamp, stamp))
        return path

    def read(self, rel):
        return (self.box.vault / rel).read_text(encoding="utf-8")

    def log(self):
        return self.read("log.md")

    def new_log_lines(self, before):
        after = self.log()
        self.assertTrue(after.startswith(before), "log.md só recebe linhas no fim")
        return [line for line in after[len(before):].splitlines() if line.strip()]

    def run_in_vault(self, *args, vault=None, config_home=None):
        return self.box.run(*args, config_home=config_home, cwd=vault or self.box.vault)

    def rel(self, path, *roots):
        p = Path(path.strip())
        if not p.is_absolute():
            return p.as_posix()
        for root in (self.box.vault, *roots):
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                continue
        self.fail(f"caminho fora do vault: {path}")

    def inbox_items(self, vault=None, config_home=None):
        out = self.run_in_vault("inbox", "list", "--json", vault=vault, config_home=config_home)
        self.assertExit(out, 0)
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")
        self.assertIsInstance(data, dict, data)
        self.assertIsInstance(data.get("items"), list, data)
        return data["items"]

    def note(self, rel):
        return fn("parse_note", "SPEC-0018")(rel, self.read(rel), None)

    def processed(self, name):
        """Caminho (relativo ao vault) do item movido para raw/processed/AAAA-MM/, conferindo a pasta do mês."""
        found = sorted(p.relative_to(self.box.vault).as_posix()
                       for p in (self.box.vault / "raw" / "processed").glob(f"*/{name}"))
        self.assertEqual(found, [f"raw/processed/{month()}/{name}"], f"{name} em raw/processed")
        return found[0]


class CaptureCliTest(InboxCliTestCase):
    def test_capture_creates_a_capture_note_in_the_inbox_and_empty_text_exits_2(self):
        """SPEC-0021:IT-01"""
        self.make_vault()
        log_before = self.log()
        days = {dt.date.today().isoformat()}
        out = self.box.run("capture", "Ideia sobre grafos", "--context", "college")
        days.add(dt.date.today().isoformat())
        self.assertExit(out, 0)
        printed = [line for line in out.stdout.splitlines() if line.strip()]
        self.assertTrue(printed, output(out))
        rel = self.rel(printed[-1])
        m = CAPTURE_NAME.match(rel)
        self.assertTrue(m, f"nome da captura fora do contrato: {rel}")
        self.assertIn(m.group(1), days)
        self.assertTrue((self.box.vault / rel).is_file())
        note = self.note(rel)
        self.assertEqual(note.frontmatter.get("type"), "capture")
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertIn(str(note.frontmatter.get("created") or "")[:10], days)
        self.assertIn("Ideia sobre grafos", note.body)
        lines = self.new_log_lines(log_before)
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], rf"^- \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} capture {re.escape(rel)}")

        before = snapshot(self.box.vault)
        for text in ("", "   "):
            with self.subTest(text=text):
                out = self.box.run("capture", text)
                self.assertExit(out, 2)
                self.assertEqual(snapshot(self.box.vault), before, "captura vazia não escreve nada")


class InboxListCliTest(InboxCliTestCase):
    def fill_inbox(self):
        self.put("inbox/ideia-antiga.md", "Ideia sobre grafos de conhecimento para o TCC. " * 6, age_days=10.04)
        self.put("inbox/aula.pdf", b"%PDF-1.4 aula", age_days=3)
        self.put("inbox/link.txt", "https://example.com/artigo-sobre-grafos\n", age_days=2)
        self.put("inbox/video.mov.icloud", b"bplist00\x01placeholder", age_days=1)

    def test_list_shows_kinds_oldest_first_and_only_the_old_note_is_stale(self):
        """SPEC-0021:IT-02"""
        self.make_vault()
        self.assertEqual(self.box.config_json()["values"].get("inbox_stale_days"), 7, "padrão do brain-config.yml")
        self.fill_inbox()
        items = self.inbox_items()
        paths = [self.rel(i["path"]) for i in items]
        self.assertEqual(paths, ["inbox/ideia-antiga.md", "inbox/aula.pdf", "inbox/link.txt",
                                 "inbox/video.mov.icloud"], "do mais antigo para o mais novo")
        by_path = dict(zip(paths, items))
        expected = {"inbox/ideia-antiga.md": ("text", True), "inbox/aula.pdf": ("file", False),
                    "inbox/link.txt": ("link", False), "inbox/video.mov.icloud": ("syncing", False)}
        for path, (kind, stale) in expected.items():
            with self.subTest(path=path):
                item = by_path[path]
                self.assertTrue({"path", "kind", "size", "age_days", "stale", "preview"} <= set(item), item)
                self.assertEqual(item["kind"], kind)
                self.assertIs(item["stale"], stale)
                self.assertEqual(item["size"], (self.box.vault / path).stat().st_size)
        note = by_path["inbox/ideia-antiga.md"]
        self.assertGreaterEqual(note["age_days"], 10)
        self.assertLess(note["age_days"], 11)
        self.assertTrue(note["preview"].startswith("Ideia sobre grafos"), note["preview"])
        self.assertLessEqual(len(note["preview"]), 120)
        for path in ("inbox/aula.pdf", "inbox/video.mov.icloud"):
            self.assertFalse(by_path[path]["preview"], f"{path} não tem prévia de texto")

    def test_stale_days_comes_from_brain_config(self):
        """SPEC-0021:IT-02"""
        self.make_vault()
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = self.box.vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        data["inbox_stale_days"] = 12
        shared.write_text(dump(data), encoding="utf-8")
        self.fill_inbox()
        self.assertEqual([i["stale"] for i in self.inbox_items()], [False, False, False, False])

    def test_empty_inbox_prints_inbox_vazia(self):
        """SPEC-0021:IT-02"""
        self.make_vault()
        out = self.run_in_vault("inbox", "list")
        self.assertExit(out, 0)
        self.assertIn("Inbox vazia", out.stdout)


class IngestMoveCliTest(InboxCliTestCase):
    def test_ingest_move_takes_the_pdf_out_of_the_inbox_into_files(self):
        """SPEC-0021:IT-03"""
        self.make_vault()
        pdf = self.put("inbox/aula.pdf", b"%PDF-1.4 aula de grafos")
        log_before = self.log()
        out = self.run_in_vault("ingest", "inbox/aula.pdf", "--move", "--context", "college", "--json")
        self.assertExit(out, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["file"], f"college/{year()}/aula.pdf")
        moved = self.box.files / "college" / year() / "aula.pdf"
        self.assertEqual(moved.read_bytes(), b"%PDF-1.4 aula de grafos")
        self.assertFalse(pdf.exists(), "o PDF saiu da inbox")
        raw = self.rel(data["raw"])
        self.assertRegex(raw, r"^raw/[^/]+\.md$")
        note = self.note(raw)
        self.assertEqual(note.frontmatter.get("type"), "source")
        self.assertEqual(note.frontmatter.get("files"), [f"college/{year()}/aula.pdf"])
        lines = self.new_log_lines(log_before)
        self.assertTrue(any(re.search(rf" ingest {re.escape(raw)}", line) for line in lines), lines)
        self.assertTrue(any("aula.pdf" in line for line in lines), lines)

        odd = self.put("inbox/Scan 30-10 às 14h (1) ✨.pdf", b"%PDF-1.4 celular")
        out = self.run_in_vault("ingest", f"inbox/{odd.name}", "--move", "--context", "college", "--json")
        self.assertExit(out, 0)
        self.assertFalse(odd.exists(), "nome com caracteres estranhos vindos do celular é aceito")
        self.assertEqual((self.box.files / json.loads(out.stdout)["file"]).read_bytes(), b"%PDF-1.4 celular")

    def test_move_outside_the_inbox_exits_2_and_plain_ingest_still_copies(self):
        """SPEC-0021:IT-03"""
        self.make_vault()
        outside = (self.put("outro/x.pdf", b"%PDF-1.4 fora", base=self.box.root),
                   self.put("raw/x.pdf", b"%PDF-1.4 raw"))
        for source in outside:
            with self.subTest(source=str(source)):
                vault_before, files_before = snapshot(self.box.vault), snapshot(self.box.root / "Drive")
                out = self.run_in_vault("ingest", source, "--move", "--context", "college")
                self.assertExit(out, 2)
                self.assertIn("--move só vale para itens da inbox", output(out))
                self.assertTrue(source.exists())
                self.assertEqual(snapshot(self.box.vault), vault_before)
                self.assertEqual(snapshot(self.box.root / "Drive"), files_before)

        kept = self.put("inbox/fica.pdf", b"%PDF-1.4 fica")
        out = self.run_in_vault("ingest", "inbox/fica.pdf", "--context", "college", "--json")
        self.assertExit(out, 0)
        self.assertEqual(kept.read_bytes(), b"%PDF-1.4 fica", "sem --move o item fica na inbox")
        self.assertEqual((self.box.files / json.loads(out.stdout)["file"]).read_bytes(), b"%PDF-1.4 fica")


class InboxDoneCliTest(InboxCliTestCase):
    def test_done_moves_text_to_raw_processed_and_logs_the_note(self):
        """SPEC-0021:IT-04"""
        self.make_vault()
        out = self.box.run("capture", "Ideia sobre grafos", "--context", "college")
        self.assertExit(out, 0)
        item = self.rel([line for line in out.stdout.splitlines() if line.strip()][-1])
        original = (self.box.vault / item).read_bytes()
        self.assertExit(self.box.run("new-note", "--type", "note", "--title", "Ideia sobre grafos",
                                     "--context", "college"), 0)
        log_before = self.log()

        out = self.run_in_vault("inbox", "done", item, "--note", "Ideia sobre grafos")
        self.assertExit(out, 0)
        name = Path(item).name
        dest = self.processed(name)
        self.assertEqual((self.box.vault / dest).read_bytes(), original, "o item é movido sem mudança")
        self.assertFalse((self.box.vault / item).exists(), "o item saiu da inbox")
        lines = self.new_log_lines(log_before)
        self.assertTrue(any(re.search(rf" inbox-done \S*{re.escape(name)} → \S*{re.escape(dest)}.*"
                                      r"nota: .*Ideia sobre grafos", line) for line in lines), lines)

        self.put("inbox/artigo.url", "[InternetShortcut]\nURL=https://example.com/grafos\n")
        self.assertExit(self.run_in_vault("inbox", "done", "inbox/artigo.url"), 0)
        self.processed("artigo.url")

    def test_done_refuses_file_syncing_missing_and_outside_items(self):
        """SPEC-0021:IT-04"""
        self.make_vault()
        self.put("inbox/aula.pdf", b"%PDF-1.4 aula")
        self.put("inbox/aula2.pdf.icloud", b"bplist00\x01placeholder")
        self.put("raw/solta.md", "Fora da inbox.\n")
        cases = (("inbox/aula.pdf", "arquivo: use ingest --move"),
                 ("inbox/aula2.pdf.icloud", "ainda sincronizando"),
                 ("inbox/nao-existe.md", None),
                 ("raw/solta.md", None),
                 ("inbox/../raw/solta.md", None))
        for item, message in cases:
            with self.subTest(item=item):
                before = snapshot(self.box.vault)
                out = self.run_in_vault("inbox", "done", item)
                self.assertExit(out, 2)
                if message:
                    self.assertIn(message, output(out))
                self.assertEqual(snapshot(self.box.vault), before, "nada se move e o log não muda")


class OtherMachineCliTest(InboxCliTestCase):
    def test_item_dropped_on_machine_a_is_stored_by_machine_b_and_the_inbox_empties(self):
        """SPEC-0021:IT-05"""
        self.make_vault()
        self.put("projects/college/Ontologias.md",
                 "---\ntype: note\ntitle: Ontologias\ncreated: 2026-01-01\ncontext: college\n---\n"
                 "# Ontologias\n\nClasses e relações.\n\n## Relations\n")
        link = self.box.root / "OtherMachine" / "Vault"
        link.parent.mkdir()
        link.symlink_to(self.box.vault, target_is_directory=True)
        machine_b = self.box.root / "config-home-b"
        self.assertExit(self.box.init("--join", vault=link, config_home=machine_b), 0)

        self.put("inbox/Ideia do celular.md", "Grafos de conhecimento ligam conceitos do curso.\n")

        def b(*args):
            out = self.run_in_vault(*args, vault=link, config_home=machine_b)
            self.assertExit(out, 0)
            return out

        items = self.inbox_items(vault=link, config_home=machine_b)
        self.assertEqual([(self.rel(i["path"], link), i["kind"]) for i in items],
                         [("inbox/Ideia do celular.md", "text")])
        item = self.rel(items[0]["path"], link)
        created = self.rel(json.loads(b("new-note", "--type", "note", "--title", "Grafos de conhecimento",
                                        "--context", "college", "--json").stdout)["path"], link)
        self.assertEqual(created, "projects/college/Grafos de conhecimento.md")
        b("relate", "Grafos de conhecimento", "Ontologias", "--why", "aplica", "--both")
        b("index", "--context", "college")
        log_before = self.log()
        b("inbox", "done", item, "--note", created)

        self.assertIn("- [[Ontologias]] — aplica", self.read(created).split("## Relations", 1)[1])
        self.assertEqual(self.note(created).frontmatter.get("context"), "college")
        self.assertIn("- [[Grafos de conhecimento]]", region(self.read("mocs/college.md"), "notes").splitlines())
        self.processed("Ideia do celular.md")
        lines = self.new_log_lines(log_before)
        self.assertTrue(any(" inbox-done " in line and "Grafos de conhecimento" in line for line in lines), lines)
        for vault, config_home in ((link, machine_b), (self.box.vault, None)):
            with self.subTest(machine="B" if config_home else "A"):
                out = self.run_in_vault("inbox", "list", vault=vault, config_home=config_home)
                self.assertExit(out, 0)
                self.assertIn("Inbox vazia", out.stdout)


if __name__ == "__main__":
    unittest.main()
