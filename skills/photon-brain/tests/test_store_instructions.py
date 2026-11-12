"""Instruções do fluxo de guardar: SKILL.md e references/note-types.md (SPEC-0019:UT-05).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala de guardar (ou store/save) com uma lista numerada de
        exatamente seis passos, nesta ordem:
          1. Classificar (classify) — tipo e contexto
          2. Guardar o bruto (raw) — `ingest`, com `--text-file`
          3. Buscar relações (relations) — `related` (e search) antes de escrever
          4. Escrever (write) — `new-note`
          5. Ligar e indexar (link/index) — `relate` com o motivo (`--why`) e `index`
          6. Reportar (report)
        e o formato da seção Relations: "## Relations" com linhas "- [[Nota]] — motivo".

    references/note-types.md
        os sete tipos da v1 (note, lecture, source, video, document, link, moc), cada um em `crase` ou num
        título, e as chaves do frontmatter comum (type, title, context, created, tags, source, files);
        cada tipo tem assets/templates/<tipo>.md com "type: <tipo>", "# {title}", "## Summary", as seções do
        tipo e "## Relations".
"""
import re
import unittest

from brain_support import SKILL

SKILL_MD = SKILL / "SKILL.md"
NOTE_TYPES_MD = SKILL / "references" / "note-types.md"
STORE_FLOW_MD = SKILL / "references" / "store-flow.md"
TEMPLATES = SKILL / "assets" / "templates"
TYPES = ("note", "lecture", "source", "video", "document", "link", "moc")
FRONTMATTER_KEYS = ("type", "title", "context", "created", "tags", "source", "files")
TYPE_SECTIONS = {"lecture": ("## Key points", "## Questions"), "video": ("## Timestamps",),
                 "document": ("## Highlights",)}
STEPS = (
    (r"classific", ()),
    (r"bruto|raw", (r"\bingest\b", r"--text-file")),
    (r"rela[cç](?:ão|ões)|relations?|related", (r"\brelated\b",)),
    (r"escrev|write", (r"\bnew-note\b",)),
    (r"ligar|indexar|link|index", (r"\brelate\b", r"\bindex\b", r"--why|motivo|reason")),
    (r"report", ()),
)


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0019)")
    return path.read_text(encoding="utf-8")


def store_section(text):
    """Corpo da primeira seção '## '/'### ' sobre guardar que tenha uma lista numerada."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if not m or not re.search(r"(?i)guardar|store|save", m.group(2)):
            continue
        level, body = len(m.group(1)), []
        for nxt in lines[i + 1:]:
            h = re.match(r"^(#{1,6}) ", nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        if any(re.match(r"^\d+\.\s", b) for b in body):
            return "\n".join(body)
    raise AssertionError("SKILL.md sem seção do fluxo de guardar com passos numerados (SPEC-0019)")


def numbered_steps(section):
    """[(número, texto)] dos itens numerados de primeiro nível (com as linhas de continuação)."""
    steps = []
    for line in section.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            steps.append([int(m.group(1)), m.group(2)])
        elif steps and line.strip() and not re.match(r"^\S", line):
            steps[-1][1] += "\n" + line
    return [tuple(step) for step in steps]


class StoreFlowInstructionsTest(unittest.TestCase):
    def test_skill_md_has_the_six_store_steps_in_order_with_the_commands(self):
        """SPEC-0019:UT-05"""
        text = read(SKILL_MD)
        steps = numbered_steps(store_section(text))
        self.assertEqual([n for n, _ in steps], [1, 2, 3, 4, 5, 6], steps)
        for (number, body), (title, commands) in zip(steps, STEPS):
            with self.subTest(step=number):
                self.assertRegex(body, rf"(?i){title}", f"passo {number}")
                for command in commands:
                    self.assertRegex(body, rf"(?i){command}", f"passo {number} sem {command}")
        self.assertIn("## Relations", text)
        self.assertRegex(text, r"- \[\[[^\]]+\]\] — \S", "formato da linha de Relations")

    def test_note_types_reference_describes_the_seven_types_with_templates(self):
        """SPEC-0019:UT-05"""
        text = read(NOTE_TYPES_MD)
        headings = [line for line in text.splitlines() if line.startswith("#")]
        for note_type in TYPES:
            with self.subTest(note_type=note_type):
                in_heading = any(re.search(rf"(?<![\w-]){note_type}(?![\w-])", h) for h in headings)
                self.assertTrue(in_heading or f"`{note_type}`" in text, f"note-types.md não descreve {note_type}")
                template = TEMPLATES / f"{note_type}.md"
                self.assertTrue(template.is_file(), f"{template} não existe")
                body = template.read_text(encoding="utf-8")
                for needle in (f"type: {note_type}", "# {title}", "## Summary", "## Relations",
                               *TYPE_SECTIONS.get(note_type, ())):
                    self.assertRegex(body, rf"(?m)^{re.escape(needle)}\s*$", f"{template}: {needle}")
        for key in FRONTMATTER_KEYS:
            self.assertRegex(text, rf"(?<![\w-]){key}(?![\w-])", f"note-types.md sem a chave {key}")


    def test_store_flow_states_the_guaranteed_index_bound(self):
        """SPEC-0019:UT-05"""
        text = read(STORE_FLOW_MD)
        self.assertNotRegex(text, r"(?i)menos de 1 s|under 1 s|< ?1 s", "o contrato garante < 3 s, não < 1 s")
        self.assertRegex(text, r"(?i)(menos de|under|<) ?3 s", "store-flow.md diz o limite garantido do index")
        self.assertRegex(text, r"5[.,]?000 notas|5[.,]?000 notes")


if __name__ == "__main__":
    unittest.main()
