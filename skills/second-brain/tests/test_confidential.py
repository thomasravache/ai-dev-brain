"""Itens confidenciais sem a CLI: referência ao cofre, marca da nota, detectores do lint e filtros da busca
(SPEC-0050: UT-01 a UT-07).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seção 6 da spec e ADR-0014):

    is_vault_ref(value) -> bool
        True só para "<esquema>://<caminho>": esquema [a-z][a-z0-9+.-]*, caminho não vazio, sem espaço no esquema.
    is_confidential(note: Note) -> bool
        True só quando o frontmatter tem `confidential: true` (o booleano YAML, sem aspas). parse_scalar não converte
        tipos, então "true" entre aspas e `yes` precisam ser distinguidos lendo o valor como está no texto.
    find_secrets(text) -> list[(linha, tipo)]
        linha = número da linha (1 a partir do início de `text`); tipo: "chave privada" | "token" | "senha rotulada".
        Nunca devolve o valor encontrado.
    find_personal_data(text, detectors=None, patterns=None) -> list[(linha, tipo)]
        detectors = nomes ligados ("cpf", "cnpj", "card", "labeled-document"; None = todos); patterns = {nome: regex
        compilada} extras. tipo: "cpf" | "cnpj" | "cartão" | "documento rotulado" | <nome do padrão>.
    compile_personal_data(lint: dict) -> (detectors, patterns, problems)
        lint = a chave `lint` do brain-config.yml ({} = padrão). detectors: lista dos ligados (padrão = os quatro);
        patterns: {nome: regex compilada} só dos válidos; problems: list[str], um por padrão inválido ou com
        quantificador aninhado (mesma proteção de compile_conflict_patterns), citando o nome do padrão.
    check_secret_in_note(notes) / check_personal_data(notes, detectors=None, patterns=None) -> list[Finding]
        rule "secret-in-note" / "personal-data", severity "warn" (LINT_SEVERITY e LINT_CHECKS registram as duas);
        só notas sem confidential: true. A linha é a do arquivo da nota (Note.text). path é o caminho da nota (os
        testes aceitam "<caminho>" ou "<caminho>:<linha>"); a linha vai no path ou no detail; o tipo no detail.
    search(..., include_confidential=False), related(..., include_confidential=False),
    build_context(..., include_confidential=False), note_links(notes, path, index, include_confidential=False)
        sem a opção a nota confidencial não aparece em resultados, vizinhas, links de saída, backlinks nem como link
        quebrado. build_context e note_links ganham "confidential_omitted": N (notas distintas omitidas).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import brain, fn

SPEC = "SPEC-0050"

# Amostras montadas por concatenação: o arquivo de teste não tem nada com cara de segredo real.
DASHES = "-" * 5
PRIVATE_KEY = (f"{DASHES}BEGIN RSA PRIV" + f"ATE KEY{DASHES}\nMIIEfakeFAKEfakeFAKEfake0050\n"
               f"{DASHES}END RSA PRIV" + f"ATE KEY{DASHES}")
GHP = "ghp" + "_" + "Ab1" * 12
AKIA = "AK" + "IA" + "TESTFAKE0050ZZZZ"
XOXB = "xo" + "xb-" + "0000000000-fakefakefake0050"
SK = "sk" + "-" + "f4k3" * 6
LABELED_1 = "senha: " + "hunter22"
LABELED_2 = "password=" + "abc123"
SECRETS = (
    (PRIVATE_KEY, "chave privada"),
    (f"use {GHP} no CI", "token"),
    (f"chave da AWS {AKIA}", "token"),
    (f"bot do Slack {XOXB}", "token"),
    (f"chave da OpenAI {SK}", "token"),
    (LABELED_1, "senha rotulada"),
    (LABELED_2, "senha rotulada"),
)
PLACEHOLDERS = ("senha: ***", "token: <seu token>", "api_key: ${KEY}", "pwd: xxx")

PERSONAL = (
    ("123.456.789-09", "cpf"),
    ("111.444.777-35", "cpf"),
    ("CPF: 12345678909", "cpf"),
    ("11.222.333/0001-81", "cnpj"),
    ("4111 1111 1111 1111", "cartão"),
    ("RG: 12.345.678-9", "documento rotulado"),
)
NOT_PERSONAL = ("123.456.789-00", "4111 1111 1111 1112", "fulano@exemplo.com", "(11) 98765-4321")
NIF = r"\bNIF:\s*\d{9}\b"


def note_text(title, body, confidential=None, extra=""):
    lines = ["---", "type: note", f"title: {title}", "created: 2026-10-01", "tags: []"]
    if confidential is not None:
        lines.append(f"confidential: {confidential}")
    return "\n".join(lines) + f"\n{extra}---\n\n# {title}\n\n{body}\n"


def parse(path, text):
    return fn("parse_note", "SPEC-0018")(path, text, None)


def kinds(found):
    """Tipos dos achados de um detector, conferindo a forma (linha, tipo)."""
    assert isinstance(found, list), f"detector devolve list, veio {type(found).__name__}"
    for item in found:
        assert len(item) == 2 and isinstance(item[0], int) and isinstance(item[1], str), item
    return [item[1] for item in found]


def finding_dict(finding):
    data = finding if isinstance(finding, dict) else finding.as_dict()
    return {name: data.get(name) for name in ("rule", "severity", "path", "detail", "suggestion")}


class VaultRefTest(unittest.TestCase):
    def test_only_scheme_and_non_empty_path_pass(self):
        """SPEC-0050:UT-01"""
        is_ref = fn("is_vault_ref", SPEC)
        for value in ("keepass://Pessoal/Banco", "bitwarden://item/abc", "op://Vault/Item"):
            with self.subTest(value=value):
                self.assertTrue(is_ref(value))
        for value in ("", "keepass:", "://x", "KeePass ://x", "banco"):
            with self.subTest(value=value):
                self.assertFalse(is_ref(value))


class ConfidentialMarkTest(unittest.TestCase):
    def test_only_the_boolean_true_marks_a_note(self):
        """SPEC-0050:UT-02"""
        is_conf = fn("is_confidential", SPEC)
        cases = (("true", True), ('"true"', False), ("yes", False), ("false", False), (None, False))
        for value, expected in cases:
            with self.subTest(confidential=value):
                note = parse("resources/Nota.md", note_text("Nota", "corpo", value))
                self.assertIs(bool(is_conf(note)), expected)


class SecretDetectorTest(unittest.TestCase):
    def test_keys_tokens_and_labeled_passwords_are_found_with_their_kind(self):
        """SPEC-0050:UT-03"""
        find = fn("find_secrets", SPEC)
        for text, kind in SECRETS:
            with self.subTest(kind=kind, text=text[:12]):
                found = find(text)
                self.assertEqual(kinds(found), [kind], found)
                self.assertEqual(found[0][0], 1)

    def test_placeholders_are_not_secrets(self):
        """SPEC-0050:UT-03"""
        find = fn("find_secrets", SPEC)
        for text in PLACEHOLDERS:
            with self.subTest(text=text):
                self.assertEqual(kinds(find(text)), [])

    def test_line_numbers_follow_the_text(self):
        """SPEC-0050:UT-03"""
        text = "\n".join(["linha comum", *PLACEHOLDERS, LABELED_1, "fim", f"use {GHP} no CI"])
        found = fn("find_secrets", SPEC)(text)
        self.assertEqual(sorted(found), [(6, "senha rotulada"), (8, "token")])


class PersonalDataDetectorTest(unittest.TestCase):
    def test_valid_documents_and_labeled_document_are_found_with_their_kind(self):
        """SPEC-0050:UT-04"""
        find = fn("find_personal_data", SPEC)
        for text, kind in PERSONAL:
            with self.subTest(text=text):
                self.assertEqual(kinds(find(text)), [kind])

    def test_wrong_check_digit_luhn_failure_email_and_phone_are_ignored(self):
        """SPEC-0050:UT-04"""
        find = fn("find_personal_data", SPEC)
        for text in NOT_PERSONAL:
            with self.subTest(text=text):
                self.assertEqual(kinds(find(text)), [])


class FindingOutputTest(unittest.TestCase):
    def test_findings_have_path_line_and_kind_but_never_the_value(self):
        """SPEC-0050:UT-05"""
        b = brain()
        for rule in ("secret-in-note", "personal-data"):
            with self.subTest(rule=rule):
                self.assertEqual(getattr(b, "LINT_SEVERITY", {}).get(rule), "warn")
                self.assertIn(rule, getattr(b, "LINT_CHECKS", {}))
        rel = "resources/Vazou.md"
        text = note_text("Vazou", f"Acesso do banco.\n{LABELED_1}\nCPF: 123.456.789-09")
        lines = text.splitlines()
        secret_line = lines.index(LABELED_1) + 1
        cpf_line = lines.index("CPF: 123.456.789-09") + 1
        notes = [parse(rel, text)]
        secret = [finding_dict(f) for f in fn("check_secret_in_note", SPEC)(notes)]
        personal = [finding_dict(f) for f in fn("check_personal_data", SPEC)(notes)]
        self.assertEqual([(f["rule"], f["severity"]) for f in secret], [("secret-in-note", "warn")], secret)
        self.assertEqual([(f["rule"], f["severity"]) for f in personal], [("personal-data", "warn")], personal)
        for found, line, kind in ((secret[0], secret_line, "senha rotulada"), (personal[0], cpf_line, "cpf")):
            with self.subTest(kind=kind):
                self.assertTrue(found["path"] in (rel, f"{rel}:{line}"), found)
                self.assertRegex(f"{found['path']} {found['detail']}", rf"(?<!\d){line}(?!\d)")
                self.assertIn(kind, found["detail"].lower())
        dumped = json.dumps(secret + personal, ensure_ascii=False) + repr(secret + personal)
        for value in ("hunter22", "123.456.789-09", "12345678909"):
            self.assertNotIn(value, dumped)

    def test_confidential_notes_are_not_judged(self):
        """SPEC-0050:UT-05"""
        text = note_text("Sigilo", f"{LABELED_1}\nCPF: 123.456.789-09", "true")
        notes = [parse("resources/Sigilo.md", text)]
        self.assertEqual(fn("check_secret_in_note", SPEC)(notes), [])
        self.assertEqual(fn("check_personal_data", SPEC)(notes), [])


class PersonalDataConfigTest(unittest.TestCase):
    def test_default_turns_on_every_detector(self):
        """SPEC-0050:UT-06"""
        detectors, patterns, problems = fn("compile_personal_data", SPEC)({})
        self.assertEqual(set(detectors), {"cpf", "cnpj", "card", "labeled-document"})
        self.assertEqual((dict(patterns), list(problems)), ({}, []))

    def test_only_enabled_detectors_and_valid_extra_patterns_run(self):
        """SPEC-0050:UT-06"""
        lint = {"personal_data": ["cpf"],
                "personal_data_patterns": {"nif": NIF, "ruim": "(abc", "lento": "(a+)+$"}}
        detectors, patterns, problems = fn("compile_personal_data", SPEC)(lint)
        self.assertEqual(list(detectors), ["cpf"])
        self.assertEqual(set(patterns), {"nif"})
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("ruim" in p for p in problems), problems)
        self.assertTrue(any("lento" in p for p in problems), problems)
        text = "CPF: 123.456.789-09\n11.222.333/0001-81\n4111 1111 1111 1111\nRG: 12.345.678-9\nNIF: 123456789"
        found = fn("find_personal_data", SPEC)(text, detectors, patterns)
        self.assertEqual(sorted(kinds(found)), ["cpf", "nif"])


COMUM = "projects/c/Conta comum.md"
SIGILOSA = "projects/c/Conta sigilosa.md"


class ConfidentialFilterTest(unittest.TestCase):
    def setUp(self):
        self.notes = [
            parse(COMUM, note_text("Conta comum", "Banco do bairro. Ver [[Conta sigilosa]].")),
            parse(SIGILOSA, note_text("Conta sigilosa", "Banco e agência da conta. Ver [[Conta comum]].", "true")),
            parse("projects/c/Outra.md", note_text("Outra", "Receita de bolo de fubá.")),
        ]

    def paths(self, items):
        return [item["path"] for item in items]

    def test_search_and_related_hide_the_confidential_note_unless_included(self):
        """SPEC-0050:UT-07"""
        search, related = fn("search", "SPEC-0018"), fn("related", "SPEC-0018")
        self.assertEqual(self.paths(search(self.notes, "banco")), [COMUM])
        self.assertIn(SIGILOSA, self.paths(search(self.notes, "banco", include_confidential=True)))
        self.assertNotIn(SIGILOSA, self.paths(related(self.notes, text="banco")))
        self.assertIn(SIGILOSA, self.paths(related(self.notes, text="banco", include_confidential=True)))
        self.assertNotIn(SIGILOSA, self.paths(related(self.notes, note=COMUM)))
        self.assertIn(SIGILOSA, self.paths(related(self.notes, note=COMUM, include_confidential=True)))

    def test_context_package_hides_the_confidential_note_and_counts_it(self):
        """SPEC-0050:UT-07"""
        build = fn("build_context", "SPEC-0020")
        data = build(self.notes, "banco")
        listed = self.paths(data["notes"]) + self.paths(data["omitted"]) + [b["note"] for b in data["broken"]]
        self.assertNotIn(SIGILOSA, listed)
        self.assertIn(COMUM, self.paths(data["notes"]))
        # o link da nota comum para a confidencial não vira "link quebrado" (o que revelaria o título)
        self.assertNotIn("Conta sigilosa", [b["target"] for b in data["broken"]], data["broken"])
        self.assertEqual(data.get("confidential_omitted"), 1, data)
        data = build(self.notes, "banco", include_confidential=True)
        self.assertIn(SIGILOSA, self.paths(data["notes"]))
        self.assertEqual(data.get("confidential_omitted", 0), 0)

    def test_note_links_hide_the_confidential_note_and_count_it(self):
        """SPEC-0050:UT-07"""
        index = fn("LinkIndex", "SPEC-0018")(n.path for n in self.notes)
        links = fn("note_links", "SPEC-0018")
        data = links(self.notes, COMUM, index)
        self.assertNotIn("sigilosa", json.dumps(data, ensure_ascii=False).lower(), data)
        self.assertEqual(data.get("confidential_omitted"), 1, data)
        data = links(self.notes, COMUM, index, include_confidential=True)
        self.assertIn(SIGILOSA, [item["path"] for item in data["outgoing"]])
        self.assertIn(SIGILOSA, data["backlinks"])
        self.assertEqual(data["broken"], [])



class ReviewRegressionTest(unittest.TestCase):
    """Regressões da revisão (G4) da SPEC-0050."""

    def test_crlf_and_bom_notes_are_still_confidential(self):
        """SPEC-0050:UT-02 — CRLF e BOM antes de "---" não escondem a marca."""
        is_conf = fn("is_confidential", SPEC)
        base = note_text("Nota", "corpo", "true")
        crlf = base.replace("\n", "\r\n")
        self.assertIn("confidential: true\r\n", crlf)
        for name, text in (("crlf", crlf), ("bom", "\ufeff" + base), ("bom+crlf", "\ufeff" + crlf)):
            with self.subTest(case=name):
                self.assertTrue(is_conf(parse("resources/Nota.md", text)))

    def test_crlf_and_bom_notes_read_from_disk_are_confidential(self):
        """SPEC-0050:UT-02"""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        read_note, is_conf = fn("read_note", "SPEC-0018"), fn("is_confidential", SPEC)
        base = note_text("Nota", "corpo", "true")
        for name, data in (("crlf", base.replace("\n", "\r\n").encode()),
                           ("bom", b"\xef\xbb\xbf" + base.encode())):
            with self.subTest(case=name):
                path = root / f"{name}.md"
                path.write_bytes(data)
                self.assertTrue(is_conf(read_note(path, f"{name}.md", None)))

    def test_card_with_all_equal_digits_is_not_personal_data(self):
        """SPEC-0050:UT-04 — passa no Luhn, mas não é um cartão."""
        find = fn("find_personal_data", SPEC)
        for text in ("0000 0000 0000 0000", "0000-0000-0000-0000", "cartão: 0000000000000000"):
            with self.subTest(text=text):
                self.assertEqual(kinds(find(text)), [])

    def test_vault_ref_with_control_characters_is_refused(self):
        """SPEC-0050:UT-01"""
        is_ref = fn("is_vault_ref", SPEC)
        for value in ("keepass://a\n", "keepass://a\nb", "keepass://a\r", "keepass://a\t", "keepass://\x00a"):
            with self.subTest(value=value):
                self.assertFalse(is_ref(value))

if __name__ == "__main__":
    unittest.main()
