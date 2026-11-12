"""Integração pela CLI: ingest, new-note, relate, index, log e a jornada de guardar (SPEC-0019: IT-01 a IT-07).

Cada teste cria o vault com o `brain.py init` real (SPEC-0017) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox); a pasta `files` é <tmp>/Drive/Vault-files. PDFs são bytes
quaisquer com extensão .pdf (nada é extraído aqui). Mensagens de erro podem ir para stdout ou stderr.

Saídas que os testes conferem (contrato da seção 6):
    ingest FONTE [--context C] [--title T] [--text-file ARQ] --json
        {"raw": caminho da nota de fonte no vault, "file": caminho relativo a files | null, "url": url | null}
        ("raw" relativo ao vault com "/"; absoluto dentro do vault também é aceito pelos testes)
        arquivo -> cópia em <files>/<contexto ou inbox>/<AAAA>/<nome>; nome existente -> <nome>-1.<ext>, -2...
        raw/<AAAA-MM-DD>-<slug>.md com frontmatter type: source, title, created, context, files: [<file>]
        (arquivo) ou source_url: <url> (URL); corpo "## Extracted text" + texto do --text-file ou "_(pending)_".
        Um segundo ingest no mesmo dia nunca sobrescreve a nota de fonte anterior (o nome da nova é livre).
        FONTE inexistente -> exit 2 "fonte não encontrada: FONTE"; files sem permissão -> exit 1, nada no vault.
    new-note --type T --title X [--context C] [--source S] [--tags a,b] [--json]
        cria <pasta do contexto | para.resources>/<X sanitizado>.md a partir de <vault>/templates/<T>.md (ou do
        modelo da skill, se o do vault não existir), com {title}, {date}, {context}, {source} preenchidos e as
        tags no frontmatter; imprime o caminho ({"path": ...} com --json; relativo ou absoluto).
        nota existente -> exit 2 "nota já existe: CAMINHO", arquivo intacto; tipo/contexto inválido -> exit 2 com
        a lista válida, nada escrito.
    relate DE PARA --why M [--both]      (DE/PARA = nome ou caminho da nota, resolvidos como em links)
        "- [[<nome de PARA>]] — M" no fim de "## Relations" de DE; repetida -> exit 0, "relação já existe",
        nada muda (nem o log); --both também em PARA apontando para DE; inexistente -> exit 2.
    index [--context C]
        mocs/<c>.md: região "notes" com "- [[Título]]" agrupadas por type (um rótulo com o type antes de cada
        grupo), ordenadas por título dentro do grupo; MOC ausente -> criado do modelo moc; região ausente ->
        acrescentada no fim. index.md: região "contexts" (uma linha por contexto com link para o MOC e o total
        de notas) e região "recent" (as 20 notas de maior created, da mais nova para a mais antiga).
        --context C: regenera só o MOC de C (os outros MOCs não mudam). Texto fora das regiões nunca muda.
    log.md: cada escrita acrescenta no fim "- AAAA-MM-DD HH:MM <comando> <caminho> [<detalhe>]", com o
        caminho relativo ao vault. ingest, new-note e relate sem --both: exatamente uma linha, começando pelo
        caminho escrito. relate --both e index: todo arquivo alterado aparece numa linha do comando (no máximo
        uma linha por arquivo alterado). Comando que falha ou não muda nada não acrescenta linha.
"""
import datetime as dt
import json
import os
import re
import time
import unittest
from pathlib import Path

from brain_support import Sandbox, fn, output, snapshot
from test_cli import CliTestCase

COLLEGE = ("--context", "college=projects/college:College")
THREE_CONTEXTS = COLLEGE + ("--context", "work=areas/work:Work", "--context", "personal=areas/personal:Personal")
TYPES = ("note", "lecture", "source", "video", "document", "link", "moc")
STORE_LOG_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \d{2}:\d{2} (ingest|new-note|relate|index) (\S.*)$")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def today():
    return dt.date.today().isoformat()


def year():
    return str(dt.date.today().year)


def region(text, name):
    m = re.search(rf"<!-- brain:begin {name} -->(.*?)<!-- brain:end {name} -->", text, re.DOTALL)
    if not m:
        raise AssertionError(f"região {name} ausente:\n{text}")
    return m.group(1)


def outside_regions(text):
    """O texto com o conteúdo de cada região gerada removido (só os marcadores ficam)."""
    return re.sub(r"(<!-- brain:begin (\S+) -->).*?(<!-- brain:end \2 -->)", r"\1\3", text, flags=re.DOTALL)


def note_text(title, note_type="note", context=None, created="2026-01-01", body=""):
    lines = ["---", f"type: {note_type}", f"title: {title}", f"created: {created}"]
    if context:
        lines.append(f"context: {context}")
    return "\n".join(lines) + f"\n---\n# {title}\n\n{body or 'Texto de ' + title + '.'}\n\n## Relations\n"


class StoreCliTestCase(CliTestCase):
    def make_vault(self, contexts=COLLEGE):
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(*contexts), 0)

    def write(self, rel, text):
        path = self.box.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read(self, rel):
        return (self.box.vault / rel).read_text(encoding="utf-8")

    def source(self, name, data):
        path = self.box.root / "entrada" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path

    def json_of(self, *args, code=0):
        out = self.box.run(*args, "--json")
        self.assertExit(out, code)
        try:
            return json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")

    def rel(self, path):
        """Caminho devolvido pela CLI como caminho relativo ao vault, com "/"."""
        p = Path(path)
        return p.relative_to(self.box.vault).as_posix() if p.is_absolute() else p.as_posix()

    def note(self, rel):
        return fn("parse_note", "SPEC-0018")(rel, self.read(rel), None)

    def vault_paths(self):
        return [p.relative_to(self.box.vault).as_posix() for p in self.box.vault.rglob("*.md")]

    def resolve(self, target):
        return fn("resolve_link", "SPEC-0018")(target, self.vault_paths())

    def raw_files(self):
        raw = self.box.vault / "raw"
        return sorted(p.name for p in raw.iterdir()) if raw.is_dir() else []

    def log(self):
        return self.read("log.md")

    def new_log_lines(self, before):
        after = self.log()
        self.assertTrue(after.startswith(before), "log.md só recebe linhas no fim")
        return [line for line in after[len(before):].splitlines() if line.strip()]

    def assertStoreLines(self, lines, command, dates):
        for line in lines:
            m = STORE_LOG_LINE.match(line)
            self.assertTrue(m, f"linha fora do formato do contrato: {line!r}")
            self.assertIn(m.group(1), dates, line)
            self.assertEqual(m.group(2), command, line)

    def run_logged(self, command, *args, json_out=False):
        """Roda um comando de escrita e devolve (resultado, linhas novas do log, arquivos do vault alterados)."""
        log_before = self.log()
        vault_before = {k: v[0] for k, v in snapshot(self.box.vault).items()}
        dates = {today()}
        out = self.box.run(command, *args, *(("--json",) if json_out else ()))
        dates.add(today())
        self.assertExit(out, 0)
        lines = self.new_log_lines(log_before)
        self.assertStoreLines(lines, command, dates)
        vault_after = {k: v[0] for k, v in snapshot(self.box.vault).items()}
        changed = sorted(k for k, data in vault_after.items()
                         if k != "log.md" and data is not None and vault_before.get(k) != data)
        return out, lines, changed


class IngestCliTest(StoreCliTestCase):
    def test_ingest_copies_without_overwriting_creates_source_notes_and_rejects_missing(self):
        """SPEC-0019:IT-01"""
        self.make_vault()
        pdf = self.source("aula.pdf", b"%PDF-1.4 primeira")
        text = self.source("texto.txt", "Limites e continuidade: definição épsilon-delta.\n")

        data = self.json_of("ingest", pdf, "--context", "college", "--text-file", text)
        self.assertTrue({"raw", "file", "url"} <= set(data), data)
        self.assertEqual(data["file"], f"college/{year()}/aula.pdf")
        self.assertIsNone(data["url"])
        copy = self.box.files / "college" / year() / "aula.pdf"
        self.assertEqual(copy.read_bytes(), b"%PDF-1.4 primeira")
        first_raw = self.rel(data["raw"])
        self.assertRegex(first_raw, rf"^raw/{today()}-[^/]+\.md$")
        first_text = self.read(first_raw)
        note = self.note(first_raw)
        self.assertEqual(note.frontmatter.get("type"), "source")
        self.assertTrue(str(note.frontmatter.get("title") or "").strip(), note.frontmatter)
        self.assertEqual(str(note.frontmatter.get("created")), today())
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertEqual(note.frontmatter.get("files"), [f"college/{year()}/aula.pdf"])
        self.assertRegex(note.body, r"## Extracted text\n+Limites e continuidade: definição épsilon-delta\.")

        pdf.write_bytes(b"%PDF-1.4 segunda")
        data = self.json_of("ingest", pdf, "--context", "college")
        self.assertEqual(data["file"], f"college/{year()}/aula-1.pdf")
        self.assertEqual(copy.read_bytes(), b"%PDF-1.4 primeira", "a primeira cópia não muda")
        self.assertEqual((self.box.files / "college" / year() / "aula-1.pdf").read_bytes(), b"%PDF-1.4 segunda")
        second_raw = self.rel(data["raw"])
        self.assertNotEqual(second_raw, first_raw)
        self.assertRegex(second_raw, rf"^raw/{today()}-[^/]+\.md$")
        self.assertEqual(self.read(first_raw), first_text, "a primeira nota de fonte não muda")
        note = self.note(second_raw)
        self.assertEqual(note.frontmatter.get("type"), "source")
        self.assertEqual(note.frontmatter.get("files"), [f"college/{year()}/aula-1.pdf"])
        self.assertRegex(note.body, r"## Extracted text\n+_\(pending\)_")

        loose = self.source("notas.txt", "sem contexto\n")
        data = self.json_of("ingest", loose)
        self.assertEqual(data["file"], f"inbox/{year()}/notas.txt")
        self.assertTrue((self.box.files / "inbox" / year() / "notas.txt").is_file())

        files_before = snapshot(self.box.files)
        data = self.json_of("ingest", "https://example.com/x")
        self.assertIsNone(data["file"])
        self.assertEqual(data["url"], "https://example.com/x")
        self.assertEqual(snapshot(self.box.files), files_before, "URL: nada é copiado")
        note = self.note(self.rel(data["raw"]))
        self.assertRegex(self.rel(data["raw"]), rf"^raw/{today()}-[^/]+\.md$")
        self.assertEqual(note.frontmatter.get("type"), "source")
        self.assertEqual(note.frontmatter.get("source_url"), "https://example.com/x")
        self.assertFalse(note.frontmatter.get("files"))
        self.assertRegex(note.body, r"## Extracted text\n+_\(pending\)_")

        raw_before, log_before = self.raw_files(), self.log()
        out = self.box.run("ingest", "inexistente.pdf")
        self.assertExit(out, 2)
        self.assertIn("fonte não encontrada: inexistente.pdf", output(out))
        self.assertEqual(self.raw_files(), raw_before)
        self.assertEqual(self.log(), log_before)


class NewNoteCliTest(StoreCliTestCase):
    def test_new_note_from_template_never_overwrites_and_validates_type_and_context(self):
        """SPEC-0019:IT-02"""
        self.make_vault()
        args = ("new-note", "--type", "lecture", "--title", "Integrais por partes", "--context", "college")
        data = self.json_of(*args, "--tags", "calculo,integrais")
        path = self.rel(data["path"])
        self.assertEqual(path, "projects/college/Integrais por partes.md")
        text = self.read(path)
        note = self.note(path)
        self.assertEqual(note.frontmatter.get("type"), "lecture")
        self.assertEqual(note.frontmatter.get("title"), "Integrais por partes")
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertEqual(str(note.frontmatter.get("created")), today())
        self.assertTrue({"calculo", "integrais"} <= set(note.tags), note.tags)
        for heading in ("# Integrais por partes", "## Summary", "## Key points", "## Questions", "## Relations"):
            self.assertRegex(text, rf"(?m)^{re.escape(heading)}\s*$")
        self.assertNotRegex(text, r"\{(title|date|context|source)\}")

        target = self.box.vault / path
        os.utime(target, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        before = (target.read_bytes(), target.stat().st_mtime_ns)
        out = self.box.run(*args)
        self.assertExit(out, 2)
        self.assertIn("nota já existe:", output(out))
        self.assertIn("Integrais por partes.md", output(out))
        self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)

        vault_before = snapshot(self.box.vault)
        out = self.box.run("new-note", "--type", "foo", "--title", "Qualquer", "--context", "college")
        self.assertExit(out, 2)
        for note_type in TYPES:
            self.assertRegex(output(out), rf"(?<![\w-]){note_type}(?![\w-])")
        out = self.box.run("new-note", "--type", "note", "--title", "Qualquer", "--context", "inexistente")
        self.assertExit(out, 2)
        self.assertIn("college", output(out))
        self.assertEqual(snapshot(self.box.vault), vault_before, "erro de validação não escreve nada")

        self.write("templates/lecture.md", '---\ntype: lecture\ntitle: "{title}"\ncontext: {context}\n'
                                           'created: {date}\n---\n\n# {title}\n\nMODELO DO VAULT em {date}\n\n'
                                           '## Relations\n')
        out = self.box.run("new-note", "--type", "lecture", "--title", "Séries de Taylor", "--context", "college")
        self.assertExit(out, 0)
        self.assertIn("Séries de Taylor.md", out.stdout)
        text = self.read("projects/college/Séries de Taylor.md")
        self.assertIn("MODELO DO VAULT em " + today(), text)
        self.assertIn("# Séries de Taylor", text)
        self.assertNotIn("## Key points", text)

        (self.box.vault / "templates" / "video.md").unlink()
        data = self.json_of("new-note", "--type", "video", "--title", "Aula gravada", "--context", "college")
        text = self.read(self.rel(data["path"]))
        self.assertRegex(text, r"(?m)^type: video\s*$")
        self.assertRegex(text, r"(?m)^## Timestamps\s*$", "sem modelo no vault, usa o da skill")


class RelateCliTest(StoreCliTestCase):
    def test_relate_appends_once_both_ways_and_rejects_missing_notes(self):
        """SPEC-0019:IT-03"""
        self.make_vault()
        for name in ("A", "B", "C"):
            self.write(f"resources/{name}.md", note_text(name))
        b_before = self.read("resources/B.md")

        out = self.box.run("relate", "A", "B", "--why", "aplica")
        self.assertExit(out, 0)
        a_text = self.read("resources/A.md")
        self.assertIn("- [[B]] — aplica", a_text.split("## Relations", 1)[1])

        log_before = self.log()
        out = self.box.run("relate", "A", "B", "--why", "aplica")
        self.assertExit(out, 0)
        self.assertIn("relação já existe", output(out))
        self.assertEqual(self.read("resources/A.md"), a_text)
        self.assertEqual(self.log(), log_before, "relação repetida não escreve nada")

        out = self.box.run("relate", "A", "C", "--why", "contradiz", "--both")
        self.assertExit(out, 0)
        a_lines = self.read("resources/A.md").splitlines()
        self.assertEqual(a_lines.count("- [[B]] — aplica"), 1)
        self.assertEqual(a_lines.count("- [[C]] — contradiz"), 1)
        c_text = self.read("resources/C.md")
        self.assertIn("- [[A]] — contradiz", c_text.split("## Relations", 1)[1])
        self.assertEqual(self.read("resources/B.md"), b_before, "B não muda")

        vault_before = snapshot(self.box.vault)
        for args in (("A", "Inexistente"), ("Inexistente", "A")):
            with self.subTest(args=args):
                out = self.box.run("relate", *args, "--why", "aplica")
                self.assertExit(out, 2)
        self.assertEqual(snapshot(self.box.vault), vault_before)


COLLEGE_NOTES = {"Derivadas": "lecture", "Limites": "lecture", "Resumo geral": "note"}
WORK_NOTES = {"Manual do deploy": "document", "Kickoff": "note"}
PERSONAL_NOTES = {"Viagem": "note"}
MOC_COLLEGE = ("---\ntype: moc\ntitle: College\n---\n# College\n\nMeu texto antes da lista, escrito à mão.\n\n"
               "<!-- brain:begin notes -->\n- [[Antiga]]\n<!-- brain:end notes -->\n\nMeu texto depois: não mexa.\n")
MOC_WORK = "---\ntype: moc\ntitle: Work\n---\n# Work\n\nMOC feito à mão, sem região.\n"
INDEX_USER = ("# Index\n\nTexto meu no índice.\n\n<!-- brain:begin contexts -->\n<!-- brain:end contexts -->\n\n"
              "entre as regiões\n\n<!-- brain:begin recent -->\n<!-- brain:end recent -->\n\nRodapé meu.\n")


class IndexCliTest(StoreCliTestCase):
    def setUp(self):
        super().setUp()
        self.make_vault(THREE_CONTEXTS)
        self.created = {}
        day = 0
        for folder, context, notes in (("projects/college", "college", COLLEGE_NOTES),
                                       ("areas/work", "work", WORK_NOTES),
                                       ("areas/personal", "personal", PERSONAL_NOTES)):
            for title, note_type in notes.items():
                day += 1
                self.add(f"{folder}/{title}.md", title, note_type, context, day)
        for i in range(19):  # 25 notas datadas: só as 20 mais novas entram em recent
            day += 1
            self.add(f"resources/Recurso {i:02d}.md", f"Recurso {i:02d}", "note", None, day)
        self.write("mocs/college.md", MOC_COLLEGE)
        self.write("mocs/work.md", MOC_WORK)
        (self.box.vault / "mocs" / "personal.md").unlink()
        self.write("index.md", INDEX_USER)

    def add(self, rel, title, note_type, context, day):
        created = (dt.date(2099, 1, 1) + dt.timedelta(days=day)).isoformat()
        self.created[rel] = created
        self.write(rel, note_text(title, note_type, context, created))

    def assertGrouped(self, text, expected):
        lines = region(text, "notes").splitlines()
        for title in expected:
            self.assertEqual(lines.count(f"- [[{title}]]"), 1, f"{title} em:\n{text}")
        pos = {title: lines.index(f"- [[{title}]]") for title in expected}
        for note_type in set(expected.values()):
            group = sorted(t for t, ty in expected.items() if ty == note_type)
            idxs = [pos[t] for t in group]
            self.assertEqual(idxs, sorted(idxs), f"{note_type}: ordem por título\n{text}")
            others = [pos[t] for t, ty in expected.items() if ty != note_type]
            self.assertFalse([o for o in others if min(idxs) < o < max(idxs)], f"{note_type} agrupado\n{text}")
            labels = [line for line in lines[:min(idxs)]
                      if not line.startswith("- [[") and re.search(rf"\b{note_type}\b", line)]
            self.assertTrue(labels, f"rótulo do type {note_type} antes do grupo\n{text}")

    def context_line(self, text, moc):
        lines = [line for line in region(text, "contexts").splitlines()
                 if any(self.resolve(t) == moc for t in WIKILINK.findall(line))]
        self.assertEqual(len(lines), 1, f"linha do contexto {moc} em:\n{text}")
        return lines[0]

    def test_index_regenerates_mocs_and_index_keeping_user_text(self):
        """SPEC-0019:IT-04"""
        out = self.box.run("index")
        self.assertExit(out, 0)

        college = self.read("mocs/college.md")
        self.assertEqual(outside_regions(college), outside_regions(MOC_COLLEGE), "texto do usuário byte a byte")
        self.assertGrouped(college, COLLEGE_NOTES)
        listed = set(WIKILINK.findall(region(college, "notes")))
        self.assertFalse(listed & (set(WORK_NOTES) | set(PERSONAL_NOTES) | {"Antiga", "Recurso 00"}), listed)

        work = self.read("mocs/work.md")
        self.assertTrue(work.startswith(MOC_WORK), "região acrescentada no fim; o resto intacto")
        self.assertGrouped(work, WORK_NOTES)

        personal = self.read("mocs/personal.md")
        self.assertRegex(personal, r"(?m)^type: moc\s*$", "MOC ausente criado do modelo moc")
        self.assertGrouped(personal, PERSONAL_NOTES)

        index = self.read("index.md")
        self.assertEqual(outside_regions(index), outside_regions(INDEX_USER), "texto do usuário byte a byte")
        self.assertRegex(self.context_line(index, "mocs/college.md"), r"(?<!\d)3(?!\d)")
        self.assertRegex(self.context_line(index, "mocs/work.md"), r"(?<!\d)2(?!\d)")
        self.context_line(index, "mocs/personal.md")
        recent = [self.resolve(t) for t in WIKILINK.findall(region(index, "recent"))]
        expected = sorted(self.created, key=self.created.get, reverse=True)[:20]
        self.assertEqual(recent, expected, "as 20 notas mais recentes pelo created, da mais nova para a mais antiga")

        work_after = self.read("mocs/work.md")
        self.add("projects/college/Integrais.md", "Integrais", "lecture", "college", 200)
        self.add("areas/work/Planejamento.md", "Planejamento", "note", "work", 201)
        out = self.box.run("index", "--context", "college")
        self.assertExit(out, 0)
        self.assertGrouped(self.read("mocs/college.md"), dict(COLLEGE_NOTES, Integrais="lecture"))
        self.assertEqual(self.read("mocs/work.md"), work_after, "index --context college não toca outro MOC")


class LogCliTest(StoreCliTestCase):
    def test_every_write_adds_its_log_line(self):
        """SPEC-0019:IT-05"""
        self.make_vault()
        pdf = self.source("aula.pdf", b"%PDF-1.4")
        text = self.source("texto.txt", "texto extraído\n")

        out, lines, changed = self.run_logged("ingest", pdf, "--context", "college", "--text-file", text,
                                              json_out=True)
        raw = self.rel(json.loads(out.stdout)["raw"])
        self.assertEqual(changed, [raw])
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(STORE_LOG_LINE.match(lines[0]).group(3).startswith(raw), lines)

        out, lines, changed = self.run_logged("ingest", "https://example.com/x", json_out=True)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(STORE_LOG_LINE.match(lines[0]).group(3).startswith(self.rel(json.loads(out.stdout)["raw"])))

        paths = {}
        for title in ("Integrais por partes", "Regra do produto", "Limites"):
            out, lines, changed = self.run_logged("new-note", "--type", "lecture", "--title", title,
                                                  "--context", "college", json_out=True)
            paths[title] = self.rel(json.loads(out.stdout)["path"])
            self.assertEqual(changed, [paths[title]])
            self.assertEqual(len(lines), 1, lines)
            self.assertTrue(STORE_LOG_LINE.match(lines[0]).group(3).startswith(paths[title]), lines)

        out, lines, changed = self.run_logged("relate", "Integrais por partes", "Regra do produto", "--why", "aplica")
        self.assertEqual(changed, [paths["Integrais por partes"]])
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(STORE_LOG_LINE.match(lines[0]).group(3).startswith(paths["Integrais por partes"]), lines)

        out, lines, changed = self.run_logged("relate", "Integrais por partes", "Limites",
                                              "--why", "pré-requisito de", "--both")
        self.assertEqual(changed, sorted([paths["Integrais por partes"], paths["Limites"]]))
        self.assertTrue(1 <= len(lines) <= len(changed), lines)
        for path in changed:
            self.assertTrue(any(path in line for line in lines), f"{path} sem linha no log: {lines}")

        out, lines, changed = self.run_logged("index")
        self.assertIn("mocs/college.md", changed)
        self.assertTrue(1 <= len(lines) <= len(changed), lines)
        for path in changed:
            self.assertTrue(any(path in line for line in lines), f"{path} sem linha no log: {lines}")

        log_before = self.log()
        for args in (("relate", "Integrais por partes", "Regra do produto", "--why", "aplica"),
                     ("new-note", "--type", "lecture", "--title", "Limites", "--context", "college"),
                     ("ingest", "inexistente.pdf")):
            self.box.run(*args)
        self.assertEqual(self.log(), log_before, "comando que falha ou não muda nada não escreve no log")

    def test_ingest_with_unwritable_files_folder_exits_1_and_creates_no_source_note(self):
        """SPEC-0019:IT-05"""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignora a permissão de escrita")
        self.make_vault()
        pdf = self.source("aula.pdf", b"%PDF-1.4")
        mode = self.box.files.stat().st_mode & 0o777
        self.box.files.chmod(0o555)
        self.addCleanup(self.box.files.chmod, mode)
        if os.access(self.box.files, os.W_OK):
            self.skipTest("o sistema de arquivos ignora a permissão de escrita")
        raw_before, log_before = self.raw_files(), self.log()
        out = self.box.run("ingest", pdf, "--context", "college")
        self.assertExit(out, 1)
        self.assertTrue(output(out).strip(), "exit 1 com a mensagem")
        self.assertEqual(self.raw_files(), raw_before, "nenhuma nota de fonte criada")
        self.assertEqual(self.log(), log_before)
        self.assertEqual(list(self.box.files.iterdir()), [])


PERF_NOTES = 5000
PERF_CONTEXTS = 5
PERF_LIMIT = 3.0


class IndexPerformanceCliTest(unittest.TestCase):
    """RNF de desempenho: index num vault de 5.000 notas em 5 contextos em menos de 3 s (time.monotonic)."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.vault.mkdir(parents=True)
        contexts = []
        for c in range(PERF_CONTEXTS):
            contexts += ["--context", f"c{c}=projects/c{c}:Contexto {c}"]
        out = self.box.init(*contexts)
        self.assertEqual(out.returncode, 0, output(out))
        types = ("note", "lecture", "document", "video", "link")
        for i in range(PERF_NOTES):
            c = i % PERF_CONTEXTS
            created = (dt.date(2020, 1, 1) + dt.timedelta(days=i % 2000)).isoformat()
            path = self.box.vault / f"projects/c{c}" / f"Nota {i:04d}.md"
            path.write_text(note_text(f"Nota {i:04d}", types[(i // PERF_CONTEXTS) % len(types)], f"c{c}", created,
                                      body=f"Conteúdo da nota {i} sobre o assunto {i % 97}. " * 8),
                            encoding="utf-8")

    def test_index_takes_under_3_seconds_on_5000_notes(self):
        """SPEC-0019:IT-06"""
        start = time.monotonic()
        out = self.box.run("index")
        elapsed = time.monotonic() - start
        self.assertEqual(out.returncode, 0, output(out))
        self.assertNotIn("Traceback", output(out))
        self.assertLess(elapsed, PERF_LIMIT, f"index levou {elapsed:.2f} s")
        for c in range(PERF_CONTEXTS):
            moc = (self.box.vault / "mocs" / f"c{c}.md").read_text(encoding="utf-8")
            listed = re.findall(r"(?m)^- \[\[Nota \d{4}\]\]$", region(moc, "notes"))
            self.assertEqual(len(listed), PERF_NOTES // PERF_CONTEXTS, f"c{c}")


SLIDES_TEXT = ("Integração por partes: vem da regra do produto da derivada, d(uv) = u dv + v du, "
               "integrada dos dois lados.\n")
PRODUCT_RULE = note_text("Regra do produto", "note", "college", "2026-01-01",
                         body="A derivada do produto u v é u' v + u v'. Regra do produto para derivadas.")


class StoreJourneyCliTest(StoreCliTestCase):
    def test_ingest_related_new_note_relate_both_and_index(self):
        """SPEC-0019:IT-07"""
        self.make_vault()
        self.write("projects/college/Regra do produto.md", PRODUCT_RULE)
        log_before = self.log()
        slides = self.source("slides.pdf", b"%PDF-1.4 slides")
        text = self.source("slides.txt", SLIDES_TEXT)

        raw = self.rel(self.json_of("ingest", slides, "--context", "college", "--text-file", text)["raw"])
        related = self.json_of("related", "--text", "regra do produto da derivada")
        self.assertIn("projects/college/Regra do produto.md", [r["path"] for r in related["results"]])

        lecture = self.rel(self.json_of("new-note", "--type", "lecture", "--title", "Integrais por partes",
                                        "--context", "college", "--source", raw)["path"])
        self.assertEqual(lecture, "projects/college/Integrais por partes.md")
        source = str(self.note(lecture).frontmatter.get("source") or "")
        self.assertEqual(self.resolve(source.strip().strip("[]")), raw, f"source da aula: {source!r}")

        out = self.box.run("relate", "Integrais por partes", "Regra do produto", "--why", "aplica", "--both")
        self.assertExit(out, 0)
        self.assertIn("- [[Regra do produto]] — aplica", self.read(lecture).split("## Relations", 1)[1])
        self.assertIn("- [[Integrais por partes]] — aplica",
                      self.read("projects/college/Regra do produto.md").split("## Relations", 1)[1])

        out = self.box.run("index", "--context", "college")
        self.assertExit(out, 0)
        notes = region(self.read("mocs/college.md"), "notes").splitlines()
        self.assertIn("- [[Integrais por partes]]", notes)
        self.assertIn("- [[Regra do produto]]", notes)

        lines = self.new_log_lines(log_before)
        parsed = [STORE_LOG_LINE.match(line) for line in lines]
        self.assertTrue(all(parsed), lines)
        by_command = {}
        for m in parsed:
            by_command.setdefault(m.group(2), []).append(m.group(3))
        self.assertEqual(set(by_command), {"ingest", "new-note", "relate", "index"}, lines)
        self.assertTrue(any(rest.startswith(raw) for rest in by_command["ingest"]), lines)
        self.assertTrue(any(rest.startswith(lecture) for rest in by_command["new-note"]), lines)
        for path in (lecture, "projects/college/Regra do produto.md"):
            self.assertTrue(any(path in rest for rest in by_command["relate"]), f"{path}: {lines}")
        self.assertTrue(any("mocs/college.md" in rest for rest in by_command["index"]), lines)


ORPHAN_BEGIN = "<!-- brain:begin notes -->"
ORPHAN_END = "<!-- brain:end notes -->"
BROKEN_MOCS = {
    "begin sem end": ("---\ntype: moc\ntitle: College\n---\n# College\n\n" + ORPHAN_BEGIN +
                      "\nTexto meu depois do begin órfão: não pode sumir.\n"),
    "end antes do begin": ("---\ntype: moc\ntitle: College\n---\n# College\n\n" + ORPHAN_END +
                           "\nTexto meu entre os marcadores.\n" + ORPHAN_BEGIN + "\nTexto meu no fim: não pode sumir.\n"),
    "região duplicada": ("---\ntype: moc\ntitle: College\n---\n# College\n\n" + ORPHAN_BEGIN + "\n- [[Velha]]\n" +
                         ORPHAN_END + "\n\nTexto meu entre as regiões.\n\n" + ORPHAN_BEGIN + "\n- [[Outra]]\n" +
                         ORPHAN_END + "\n\nRodapé meu.\n"),
}
EVIL_CONTEXT = "../../escaped"  # nome que sobe dois níveis: de <files> e de <vault>/mocs cai dentro do sandbox


def contents(root):
    return {k: v[0] for k, v in snapshot(root).items()}


class ReviewRegressionCliTest(StoreCliTestCase):
    """Defeitos reproduzidos na revisão da SPEC-0019 (contrato seção 6 e NFRs seção 5)."""

    def test_index_refuses_a_moc_with_unbalanced_or_duplicated_markers(self):
        """SPEC-0019:IT-04"""
        self.make_vault()
        self.write("projects/college/Derivadas.md", note_text("Derivadas", "lecture", "college"))
        self.assertExit(self.box.run("index"), 0)
        for label, broken in BROKEN_MOCS.items():
            with self.subTest(case=label):
                moc = self.write("mocs/college.md", broken)
                raw = moc.read_bytes()
                before = contents(self.box.vault)
                for attempt in (1, 2):
                    out = self.box.run("index")
                    self.assertNotEqual(out.returncode, 0, f"tentativa {attempt}: {output(out)}")
                    self.assertNotIn("Traceback", output(out))
                    self.assertIn("mocs/college.md", output(out), "o erro nomeia o arquivo")
                    self.assertEqual(moc.read_bytes(), raw, f"tentativa {attempt}: MOC byte a byte")
                    self.assertEqual(contents(self.box.vault), before, f"tentativa {attempt}: nada escrito nem logado")

    def add_evil_context(self):
        config = self.box.vault / "brain-config.yml"
        text = config.read_text(encoding="utf-8")
        line = "  college: {folder: projects/college, title: College}\n"
        self.assertIn(line, text)
        config.write_text(text.replace(line, line + f"  {EVIL_CONTEXT}: {{folder: projects/escaped, "
                                                   "title: Escaped}\n"), encoding="utf-8")

    def escaped(self):
        return sorted(p.relative_to(self.box.root).as_posix() for p in self.box.root.rglob("*escaped*")
                      if p.name != "brain-config.yml")

    def test_context_name_climbing_out_of_files_or_vault_is_refused(self):
        """SPEC-0019:IT-01"""
        self.make_vault()
        self.add_evil_context()
        pdf = self.source("f.pdf", b"%PDF-1.4")
        vault_before, files_before = contents(self.box.vault), contents(self.box.files)
        out = self.box.run("ingest", pdf, "--context", EVIL_CONTEXT)
        self.assertExit(out, 2)
        self.assertEqual(self.escaped(), [], "nada escrito fora da pasta files")
        self.assertEqual(contents(self.box.files), files_before)
        self.assertEqual(contents(self.box.vault), vault_before, "nenhuma nota de fonte nem linha de log")

    def test_index_never_writes_a_moc_outside_the_vault_for_a_hand_edited_context_name(self):
        """SPEC-0019:IT-04"""
        self.make_vault()
        self.add_evil_context()
        for args in (("index",), ("index", "--context", EVIL_CONTEXT)):
            with self.subTest(args=args):
                out = self.box.run(*args)
                self.assertNotIn("Traceback", output(out))
                self.assertEqual(self.escaped(), [], f"MOC fora do vault: {output(out)}")
                self.assertIn(EVIL_CONTEXT, output(out), "o contexto recusado aparece no erro")
                if len(args) > 1:
                    self.assertExit(out, 2)

    def test_title_with_markers_quotes_and_hash_is_kept_literally_and_readable(self):
        """SPEC-0019:IT-02"""
        self.make_vault()
        title = 'Aula "1": {date} {context} {source} #tag'
        data = self.json_of("new-note", "--type", "lecture", "--title", title, "--context", "college")
        path = self.rel(data["path"])
        text = self.read(path)
        self.assertRegex(text, rf"(?m)^# {re.escape(title)}\s*$", "o título entra literal no cabeçalho")
        note = self.note(path)
        self.assertEqual(note.warnings, [], "o frontmatter criado é lido pelo parser da skill")
        self.assertEqual(note.frontmatter.get("title"), title)
        self.assertEqual(note.frontmatter.get("type"), "lecture")
        self.assertEqual(note.frontmatter.get("context"), "college")
        found = self.json_of("search", "Aula", "--type", "lecture", "--context", "college")
        self.assertIn(path, [self.rel(r["path"]) for r in found["results"]], found)
        self.assertExit(self.box.run("index", "--context", "college"), 0)
        notes = region(self.read("mocs/college.md"), "notes")
        self.assertRegex(notes, r"(?m)^#* *lecture\s*$", notes)
        self.assertIn(Path(path).stem, notes)

    def test_very_long_title_is_refused_or_truncated_without_errno(self):
        """SPEC-0019:IT-02"""
        self.make_vault()
        out = self.box.run("new-note", "--type", "note", "--title", "Título longo " + "x" * 287, "--json")
        text = output(out)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("Errno", text, "erro do sistema cru não é mensagem para o usuário")
        if out.returncode == 0:
            path = self.box.vault / self.rel(json.loads(out.stdout)["path"])
            self.assertTrue(path.is_file(), path)
            self.assertLessEqual(len(path.name.encode("utf-8")), 255, path.name)
        else:
            self.assertEqual(out.returncode, 2, text)
            self.assertIn("título", text)

    def test_relation_with_alias_counts_as_existing(self):
        """SPEC-0019:IT-03"""
        self.make_vault()
        self.write("resources/A.md", note_text("A") + "\n- [[B|Bee]] — aplica\n")
        self.write("resources/B.md", note_text("B"))
        before = contents(self.box.vault)
        out = self.box.run("relate", "A", "B", "--why", "aplica")
        self.assertExit(out, 0)
        self.assertIn("relação já existe", output(out))
        self.assertEqual(contents(self.box.vault), before, "nada muda (nem o log)")

    def assertCrlf(self, path):
        data = path.read_bytes()
        self.assertNotRegex(data, rb"(?<!\r)\n", f"{path.name}: fim de linha misturado\n{data!r}")

    def write_crlf(self, rel, text):
        path = self.box.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        return path

    def test_relate_keeps_crlf_files_crlf(self):
        """SPEC-0019:IT-03"""
        self.make_vault()
        a = self.write_crlf("projects/college/A.md", note_text("A", "note", "college"))
        b = self.write_crlf("projects/college/B.md", note_text("B", "note", "college"))
        self.assertExit(self.box.run("relate", "A", "B", "--why", "aplica", "--both"), 0)
        self.assertIn("- [[B]] — aplica", self.read("projects/college/A.md"))
        self.assertCrlf(a)
        self.assertCrlf(b)

    def test_index_keeps_crlf_files_crlf(self):
        """SPEC-0019:IT-04"""
        self.make_vault()
        self.write("projects/college/A.md", note_text("A", "note", "college"))
        moc = self.write_crlf("mocs/college.md", MOC_COLLEGE)
        index = self.write_crlf("index.md", INDEX_USER)
        self.assertExit(self.box.run("index", "--context", "college"), 0)
        self.assertIn("[[A]]", self.read("mocs/college.md"))
        self.assertCrlf(moc)
        self.assertCrlf(index)

    def test_ingest_with_unwritable_raw_names_the_copied_file(self):
        """SPEC-0019:IT-05"""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignora a permissão de escrita")
        self.make_vault()
        pdf = self.source("aula.pdf", b"%PDF-1.4")
        raw = self.box.vault / "raw"
        mode = raw.stat().st_mode & 0o777
        raw.chmod(0o555)
        self.addCleanup(raw.chmod, mode)
        if os.access(raw, os.W_OK):
            self.skipTest("o sistema de arquivos ignora a permissão de escrita")
        log_before = self.log()
        out = self.box.run("ingest", pdf, "--context", "college")
        self.assertExit(out, 1)
        self.assertIn(f"college/{year()}/aula.pdf", output(out), "a mensagem diz onde ficou a cópia")
        self.assertEqual(self.raw_files(), [])
        self.assertEqual(self.log(), log_before)

    def test_invalid_created_date_never_goes_above_valid_recent_notes(self):
        """SPEC-0019:IT-04"""
        self.make_vault()
        for i, created in enumerate(("2026-01-01", "2026-03-01", "2026-05-01")):
            self.write(f"resources/Valida {i}.md", note_text(f"Valida {i}", created=created))
        self.write("resources/Invalida.md", note_text("Invalida", created="2026-13-45"))
        self.assertExit(self.box.run("index"), 0)
        recent = [self.resolve(t) for t in WIKILINK.findall(region(self.read("index.md"), "recent"))]
        valid = ["resources/Valida 2.md", "resources/Valida 1.md", "resources/Valida 0.md"]
        self.assertEqual(recent[:3], valid, f"data inválida fora da ordem dos recentes: {recent}")

    def symlinked(self, rel, text):
        real = self.box.root / "fora" / Path(rel).name
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(text, encoding="utf-8")
        link = self.box.vault / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists():
            link.unlink()
        link.symlink_to(real)
        return link, real

    def assertStillSymlink(self, args, link):
        out = self.box.run(*args)
        self.assertNotIn("Traceback", output(out))
        self.assertIn(out.returncode, (0, 2), output(out))
        self.assertTrue(link.is_symlink(), f"{args[0]} trocou o link simbólico por um arquivo comum: {output(out)}")

    def test_relate_never_replaces_a_symlinked_note_with_a_regular_file(self):
        """SPEC-0019:IT-03"""
        self.make_vault()
        link, _ = self.symlinked("projects/college/A.md", note_text("A", "note", "college"))
        self.write("projects/college/B.md", note_text("B", "note", "college"))
        self.assertStillSymlink(("relate", "A", "B", "--why", "aplica"), link)

    def test_index_never_replaces_a_symlinked_moc_with_a_regular_file(self):
        """SPEC-0019:IT-04"""
        self.make_vault()
        self.write("projects/college/B.md", note_text("B", "note", "college"))
        moc, _ = self.symlinked("mocs/college.md", MOC_COLLEGE)
        self.assertStillSymlink(("index", "--context", "college"), moc)


if __name__ == "__main__":
    unittest.main()
