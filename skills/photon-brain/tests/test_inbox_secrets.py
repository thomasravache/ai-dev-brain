"""Segredo na inbox sem a CLI: o detector `secret_spans`, o detector de hoje e as instruções do agente
(SPEC-0112: CH-01, UT-01, UT-02, UT-06).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seção 6 da spec e ADR-0014):

    secret_spans(text) -> list[(início, fim)]
        posições (índices de `text`, fim exclusivo) de cada valor detectado: o valor de um rótulo
        (senha|password|passwd|pwd|pin|token|api key|secret|segredo, com até três palavras entre o rótulo e o `:`/`=`,
        e `[*_]*` do negrito), `pin` seguido de 4 a 8 dígitos sem `:`, um token de prefixo conhecido e a chave
        privada. text[início:fim] cobre só o valor (nunca o rótulo). Sobreposição é aceita (o token "sk-..." depois de
        "token da api =" casa pelas duas regras). Marcadores (SECRET_PLACEHOLDER_RE) e valor com menos de
        SECRET_MIN caracteres não contam.
    find_secrets(text) e check_secret_in_note(notes): como hoje (CH-01).

Valores falsos, montados por concatenação: nada aqui é um segredo real.
"""
import re
import unittest

from brain_support import SKILL, fn
from test_confidential import PLACEHOLDERS, SECRETS, kinds, note_text, parse

SPEC = "SPEC-0112"
SK = "sk" + "-" + "abcdefghijklmnopqrstu"
# (texto, valor que as posições precisam cobrir)
LABELED = (
    ("Senha do wifi: " + "abc12345", "abc12345"),
    ("- **Senha do banco:** " + "x9y8z7w6", "x9y8z7w6"),
    ("token da api = " + SK, SK),
    ("PIN " + "1234", "1234"),
    ("pin: " + "482910", "482910"),
)
NOT_SECRETS = ("senha: ***", "senha: <a sua>", "a senha é forte", "PIN 12", "o token do evento foi bom",
               "senha do wifi da casa: " + "abc12345")  # o último: quatro palavras antes do ":"
DOCS = (SKILL / "references" / "confidential.md", SKILL / "references" / "maintenance.md",
        SKILL / "references" / "inbox.md", SKILL / "SKILL.md")
NEVER = r"nunca|never|jamais|do not|don't"
SECRET = r"senha|token|segredo|password|secret|\bpin\b"


def spans(text):
    """secret_spans(text), conferindo a forma: lista de pares (início, fim) dentro do texto."""
    found = fn("secret_spans", SPEC)(text)
    assert isinstance(found, list), f"secret_spans devolve list, veio {type(found).__name__}"
    for item in found:
        start, end = item
        assert isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text), (item, text)
    return found


def covered(found):
    return {i for start, end in found for i in range(start, end)}


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe ({SPEC})")
    return path.read_text(encoding="utf-8")


def lines_with(text, *needles):
    """Linhas (ou itens de lista) que casam com todos os regex, sem diferenciar caixa."""
    return [line for line in text.splitlines() if all(re.search(f"(?i){n}", line) for n in needles)]


class TodayDetectorTest(unittest.TestCase):
    """Caracterização: passa antes da mudança."""

    def test_today_cases_keep_their_result(self):
        """SPEC-0112:CH-01"""
        # SPEC-0112:CH-01
        find = fn("find_secrets", "SPEC-0050")
        for text, kind in SECRETS:
            with self.subTest(kind=kind, text=text[:12]):
                self.assertEqual(kinds(find(text)), [kind])
        for text in PLACEHOLDERS:
            with self.subTest(text=text):
                self.assertEqual(kinds(find(text)), [])

    def test_confidential_note_stays_out_of_secret_in_note(self):
        """SPEC-0112:CH-01"""
        # SPEC-0112:CH-01
        check = fn("check_secret_in_note", "SPEC-0050")
        body = "senha: " + "hunter22"
        common = parse("resources/Comum.md", note_text("Comum", body))
        secret = parse("resources/Sigilo.md", note_text("Sigilo", body, "true"))
        found = check([common, secret])
        paths = [(f if isinstance(f, dict) else f.as_dict())["path"] for f in found]
        self.assertEqual(len(paths), 1, paths)
        self.assertTrue(paths[0].startswith("resources/Comum.md"), paths)
        self.assertNotIn("hunter22", repr([f if isinstance(f, dict) else f.as_dict() for f in found]))


class SecretSpansTest(unittest.TestCase):
    def test_labels_with_words_and_pin_cover_only_the_value(self):
        """SPEC-0112:UT-01"""
        # SPEC-0112:UT-01
        for text, value in LABELED:
            with self.subTest(text=text):
                found = spans(text)
                self.assertTrue(found, f"nada achado em {text!r}")
                start = text.index(value)
                self.assertEqual(covered(found), set(range(start, start + len(value))),
                                 f"as posições cobrem só o valor: {[text[s:e] for s, e in found]}")

    def test_a_line_of_today_is_also_found_by_secret_spans(self):
        """SPEC-0112:UT-01 — um detector só para o lint e para a prévia"""
        # SPEC-0112:UT-01
        for text, kind in SECRETS:
            with self.subTest(kind=kind, text=text[:12]):
                self.assertTrue(spans(text), text[:12])
        found = spans("senha: " + "hunter22")
        self.assertEqual(["senha: hunter22"[s:e] for s, e in found], ["hunter22"])

    def test_spans_follow_the_whole_text(self):
        """SPEC-0112:UT-01 — posições no texto inteiro, não na linha"""
        # SPEC-0112:UT-01
        text = "linha comum\nSenha do wifi: " + "abc12345" + "\nfim\nPIN " + "4821" + "\n"
        found = spans(text)
        self.assertEqual(sorted(text[s:e] for s, e in found), ["4821", "abc12345"])

    def test_markers_prose_short_pins_and_four_words_are_not_secrets(self):
        """SPEC-0112:UT-02"""
        # SPEC-0112:UT-02
        for text in (*NOT_SECRETS, *PLACEHOLDERS):
            with self.subTest(text=text):
                self.assertEqual(spans(text), [])


class InboxSecretInstructionsTest(unittest.TestCase):
    def test_docs_send_an_inbox_secret_to_the_vault_with_the_reference(self):
        """SPEC-0112:UT-06"""
        # SPEC-0112:UT-06
        rules = {
            "item da inbox com segredo vai para o cofre com --confidential/secret-ref":
                (r"inbox", SECRET, r"cofre|gerenciador|password manager", r"--confidential|secret-ref"),
            "o valor nunca entra numa nota nem numa resposta":
                (NEVER, SECRET + r"|valor|value", r"nota|note", r"resposta|answer|reply|respond"),
        }
        for path in DOCS:
            text = read(path)
            for rule, needles in rules.items():
                with self.subTest(doc=path.relative_to(SKILL).as_posix(), rule=rule):
                    self.assertTrue(lines_with(text, *needles), f"{rule}: nenhuma linha com {needles}")


if __name__ == "__main__":
    unittest.main()
