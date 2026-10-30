"""Instruções do fluxo de consultar: SKILL.md e o modelo assets/templates/answer.md (SPEC-0020:UT-03).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala de consultar (ou query/ask/perguntar) com uma lista numerada de
        exatamente quatro passos, nesta ordem:
          1. Buscar (search) — o comando `context` (com `--context` quando a pergunta é de um contexto)
          2. Ler e seguir links (read/follow) — `related` / `links` nas notas centrais
          3. Responder (answer) — citar `[[nota]]` em cada afirmação do vault, marcar o que é conhecimento geral e
             apontar lacunas (gaps)
          4. Oferecer salvar (offer to save) — com o sim do usuário, `new-note --type answer`, `relate` com as notas
             citadas e `index`
        e a tabela de comandos com o `context QUERY`.

    assets/templates/answer.md
        frontmatter com "type: answer", title, context, created, question e cites; corpo com "# {title}" e as
        seções "## Question", "## Answer", "## Gaps" e "## Relations", nesta ordem.

    references/note-types.md (seção 8 da spec: o tipo answer é acrescentado) descreve `answer`.
"""
import re
import unittest

from brain_support import SKILL
from test_store_instructions import numbered_steps, read

SKILL_MD = SKILL / "SKILL.md"
NOTE_TYPES_MD = SKILL / "references" / "note-types.md"
ANSWER_TEMPLATE = SKILL / "assets" / "templates" / "answer.md"
STEPS = (
    (r"buscar|search", (r"(?:brain\.py |`)context\b",)),
    (r"ler|read|seguir|follow", (r"\brelated\b|\blinks\b",)),
    (r"respond|answer", (r"cit\w*[^\n]*\[\[[^\]]+\]\]|\[\[[^\]]+\]\][^\n]*cit",
                         r"conhecimento geral|general knowledge",
                         r"lacuna|gap")),
    (r"salvar|save|guardar", (r"\bsim\b|\byes\b|confirm|aceit|autoriz|consent",
                              r"new-note[^\n]*--type answer|--type answer[^\n]*new-note",
                              r"\brelate\b", r"\bindex\b")),
)
ANSWER_SECTIONS = ("## Question", "## Answer", "## Gaps", "## Relations")
ANSWER_KEYS = ("title", "context", "created", "question", "cites")


def query_section(text):
    """Corpo da primeira seção '## '/'### ' sobre consultar que tenha uma lista numerada."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if not m or not re.search(r"(?i)consult|query|ask\b|pergunt", m.group(2)):
            continue
        level, body = len(m.group(1)), []
        for nxt in lines[i + 1:]:
            h = re.match(r"^(#{1,6}) ", nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        if any(re.match(r"^\d+\.\s", b) for b in body):
            return "\n".join(body)
    raise AssertionError("SKILL.md sem seção do fluxo de consultar com passos numerados (SPEC-0020)")


def frontmatter_block(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise AssertionError(f"{ANSWER_TEMPLATE} sem frontmatter")
    return m.group(1)


class QueryFlowInstructionsTest(unittest.TestCase):
    def test_skill_md_has_the_four_query_steps_in_order_with_citation_rules(self):
        """SPEC-0020:UT-03"""
        text = read(SKILL_MD)
        steps = numbered_steps(query_section(text))
        self.assertEqual([n for n, _ in steps], [1, 2, 3, 4], steps)
        for (number, body), (title, rules) in zip(steps, STEPS):
            with self.subTest(step=number):
                self.assertRegex(body, rf"(?i){title}", f"passo {number}")
                for rule in rules:
                    self.assertRegex(body, rf"(?i){rule}", f"passo {number} sem {rule}")
        self.assertRegex(steps[0][1], r"--context", "passo 1: --context quando a pergunta é de um contexto")
        self.assertRegex(text, r"(?m)^\|\s*`context QUERY", "tabela de comandos com o context")

    def test_answer_template_has_the_contract_frontmatter_and_sections_in_order(self):
        """SPEC-0020:UT-03"""
        if not ANSWER_TEMPLATE.is_file():
            self.fail(f"{ANSWER_TEMPLATE} não existe (SPEC-0020)")
        text = ANSWER_TEMPLATE.read_text(encoding="utf-8")
        head = frontmatter_block(text)
        self.assertRegex(head, r"(?m)^type: answer\s*$")
        for key in ANSWER_KEYS:
            self.assertRegex(head, rf"(?m)^{key}\s*:", f"frontmatter sem {key}")
        self.assertRegex(text, r"(?m)^# \{title\}\s*$")
        positions = []
        for heading in ANSWER_SECTIONS:
            m = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
            self.assertTrue(m, f"answer.md sem {heading}")
            positions.append(m.start())
        self.assertEqual(positions, sorted(positions), "seções na ordem Question, Answer, Gaps, Relations")

    def test_note_types_reference_describes_answer(self):
        """SPEC-0020:UT-03"""
        text = read(NOTE_TYPES_MD)
        headings = [line for line in text.splitlines() if line.startswith("#")]
        in_heading = any(re.search(r"(?<![\w-])answer(?![\w-])", h) for h in headings)
        self.assertTrue(in_heading or "`answer`" in text, "note-types.md não descreve answer")


if __name__ == "__main__":
    unittest.main()
