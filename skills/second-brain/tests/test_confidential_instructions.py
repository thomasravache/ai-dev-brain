"""Instruções do agente para itens confidenciais: SKILL.md e references/confidential.md (SPEC-0050:UT-08).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês e leem linha a linha, ou seja,
cada regra numa frase/item de lista):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala de itens confidenciais (confidencial/confidential/segredo/
        senha/secret) que cita references/confidential.md e traz as regras do agente:
          - nunca escrever senha, token ou chave no vault, nem na inbox (pelo conector);
          - quando a pessoa der um segredo, não guardar, sugerir o gerenciador de senhas e oferecer a secret-ref;
          - `--include-confidential` só quando a pessoa pedir;
          - no modo só conector, um arquivo confidencial não é citado nem resumido;
          - nunca abrir o arquivo do gerenciador de senhas (.kdbx e outros).
    references/confidential.md
        o KeePass/KeePassXC como exemplo e o formato <esquema>://<caminho> para outros gerenciadores; a recomendação
        de anexar o documento muito sensível no próprio gerenciador; as regras secret-in-note e personal-data, os
        falsos positivos e os padrões extras (personal_data_patterns).
"""
import re
import unittest

from brain_support import SKILL

SKILL_MD = SKILL / "SKILL.md"
CONFIDENTIAL_MD = SKILL / "references" / "confidential.md"
NEVER = r"nunca|never|não |jamais|do not|don't"
SECRET = r"senha|token|chave|segredo|password|secret|\bkey\b"
TITLE = r"confiden|segredo|senha|secret|password"


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0050)")
    return path.read_text(encoding="utf-8")


def sections(text, title_re):
    """Corpos das seções '## '/'### ' cujo título casa com title_re (com os subtítulos); o título vai junto."""
    lines, found = text.splitlines(), []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if not m or not re.search(rf"(?i){title_re}", m.group(2)):
            continue
        level, body = len(m.group(1)), [line]
        for nxt in lines[i + 1:]:
            h = re.match(r"^(#{1,6}) ", nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        found.append("\n".join(body))
    return found


def lines_with(text, *needles):
    """Linhas (ou itens de lista com continuação) que casam com todos os regex, sem diferenciar caixa."""
    return [line for line in text.splitlines() if all(re.search(f"(?i){n}", line) for n in needles)]


class SkillInstructionsTest(unittest.TestCase):
    def section(self):
        found = [s for s in sections(read(SKILL_MD), TITLE) if "confidential.md" in s]
        self.assertTrue(found, "SKILL.md sem seção de itens confidenciais que cite references/confidential.md")
        return "\n".join(found)

    def test_skill_md_has_the_agent_rules(self):
        """SPEC-0050:UT-08"""
        text = self.section()
        rules = {
            "nunca escrever segredo no vault": (NEVER, SECRET, r"vault|cofre do obsidian|nota"),
            "nem na inbox (conector)": (NEVER, SECRET, r"inbox"),
            "sugerir o gerenciador e oferecer secret-ref": (r"gerenciador|password manager|manager", r"secret-ref"),
            "--include-confidential só a pedido": (r"--include-confidential", r"ped|pedir|asks?|request"),
            "conector: não citar nem resumir": (r"conector|connector", r"cit|quote|cite", r"resum|summar"),
            "nunca abrir o arquivo do gerenciador": (NEVER, r"abr|open", r"\.kdbx|gerenciador|manager"),
        }
        for rule, needles in rules.items():
            with self.subTest(rule=rule):
                self.assertTrue(lines_with(text, *needles), f"{rule}: nenhuma linha com {needles}")


class ConfidentialReferenceTest(unittest.TestCase):
    def test_reference_documents_manager_format_attachments_and_lint_rules(self):
        """SPEC-0050:UT-08"""
        text = read(CONFIDENTIAL_MD)
        checks = {
            "KeePass": r"\bKeePass\b",
            "KeePassXC": r"\bKeePassXC\b",
            "formato <esquema>://<caminho>": r"<esquema>://<caminho>|<scheme>://<path>",
            "exemplo keepass://": r"keepass://\S",
            "anexar no gerenciador": r"anex|attach",
            "secret-in-note": r"secret-in-note",
            "personal-data": r"personal-data",
            "falsos positivos": r"falsos? positivos?|false positives?",
            "padrões extras": r"personal_data_patterns",
        }
        for name, pattern in checks.items():
            with self.subTest(item=name):
                self.assertRegex(text, rf"(?i){pattern}" if name not in ("KeePass", "KeePassXC") else pattern)
        self.assertTrue(lines_with(text, r"anex|attach", r"gerenciador|manager|keepass"),
                        "recomendação de anexar o documento no próprio gerenciador")


if __name__ == "__main__":
    unittest.main()
