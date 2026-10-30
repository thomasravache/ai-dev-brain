"""Configuração em duas camadas, validação do init e YAML próprio do brain.py (SPEC-0017: UT-01 a UT-04).

Contrato esperado das funções puras de scripts/brain.py (o Implementer segue estes testes):

    PROVIDERS = ("google-drive", "onedrive", "icloud", "local")

    parse_yaml(text: str) -> dict
        Subconjunto de YAML no estilo do parse_yaml_subset da sdd-management, escrito no próprio brain.py
        (ADR-0007): `chave: valor`, mapas aninhados por indentação, mapas inline `{a: b, c: {}}` (inclusive `{}`
        vazio), listas inline `[a, b]` e em bloco (`- item`), comentários de linha inteira e no fim da linha
        (` # ...`, fora de aspas), strings com `:` (sem aspas quando o `:` não é seguido de espaço, ou entre
        aspas duplas/simples, com `''` como aspa simples escapada). Escalares são strings (não há conversão
        de tipo); o teste só compara `str(version)`.

    dump_yaml(data: dict) -> str
        Escritor do mesmo subconjunto: parse_yaml(dump_yaml(d)) == d para dicts de strings, listas de strings
        e dicts aninhados (inclusive vazios). Coloca aspas quando o valor precisa (`: `, ` #`, aspas, início
        com caractere especial).

    load_config(config_home: Path | str | None = None) -> dict
        Lê <config_home>/config.yml (local: vault, files, provider; None = $BRAIN_CONFIG_HOME ou
        ~/.config/second-brain) e <vault>/brain-config.yml (compartilhada), completa com os padrões do contrato
        e devolve {"values": {...}, "origins": {...}}:
          values  : configuração efetiva — vault, files, provider (strings, como gravadas na local), version,
                    language, layout {inbox, raw, mocs, templates, index, log}, para {...}, contexts
                    {nome: {folder, title}}, processors {...}.
          origins : origem de cada valor, "local" | "vault" | "padrão", por caminho com ponto: "vault", "files",
                    "provider", "version", "language", "contexts", "processors" e uma entrada por chave de
                    layout e para ("layout.inbox", "para.projects", ...).
        `brain.py config --json` imprime exatamente esse objeto em JSON.
        (v2) Valor de layout, para ou contexts.<c>.folder absoluto ou com ".." -> exceção com
        "brain-config.yml: <chave> fora do vault" (código 1 na CLI) — UT-07 em test_amendment_v2.

    validate_init_args(vault: str, files: str, provider: str) -> str | None
        Validação pura (sem I/O) dos argumentos de init. Devolve a mensagem de erro do contrato ou None:
          files dentro do vault (comparação por partes do caminho, não por prefixo de texto)
              -> "files precisa ficar fora do vault"
          provider fora de PROVIDERS -> mensagem que cita o provider recebido e os quatro válidos.
        A CLI imprime a mensagem e sai com 2.

    render_brain_config(vault: str, layout: dict | None = None, contexts: dict | None = None) -> str
        Texto do brain-config.yml que init grava para o vault: assets/brain-config.yml com os comentários
        mantidos; só os valores de --map e --context mudam (contrato v2, IT-10).
        layout   : sobrescritas de --map (chave de layout ou de para -> pasta relativa ao vault).
        contexts : {nome: {"folder": pasta relativa, "title": título}} vindos de --context.
        Nunca contém caminho absoluto (o caminho do vault só fica na configuração local).
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import fn

ABSOLUTE = re.compile(r"^(/|~|[A-Za-z]:[\\/]|\\\\)")


def leaves(value, path=""):
    """(caminho, valor) de cada escalar de um dict/list aninhado."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from leaves(item, f"{path}[{i}]")
    else:
        yield path, value


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vault = self.tmp / "Vault"
        self.files = self.tmp / "Vault-files"
        self.vault.mkdir()
        self.files.mkdir()
        self.config_home = self.tmp / "config-home"
        self.config_home.mkdir()
        (self.config_home / "config.yml").write_text(
            f'vault: "{self.vault}"\nfiles: "{self.files}"\nprovider: icloud\n', encoding="utf-8")
        (self.vault / "brain-config.yml").write_text(
            "version: 1\n"
            "language: auto\n"
            "layout:\n"
            "  raw: raw\n"
            "contexts:\n"
            "  college:\n"
            "    folder: projects/college\n"
            "    title: College\n",
            encoding="utf-8")

    def test_effective_config_reports_the_origin_of_each_value(self):
        """SPEC-0017:UT-01"""
        config = fn("load_config")(self.config_home)
        values, origins = config["values"], config["origins"]
        self.assertEqual(values["vault"], str(self.vault))
        self.assertEqual(origins["vault"], "local")
        self.assertEqual(values["files"], str(self.files))
        self.assertEqual(origins["files"], "local")
        self.assertEqual(values["provider"], "icloud")
        self.assertEqual(origins["provider"], "local")
        self.assertEqual(values["contexts"], {"college": {"folder": "projects/college", "title": "College"}})
        self.assertEqual(origins["contexts"], "vault")
        self.assertEqual(values["layout"]["raw"], "raw")
        self.assertEqual(origins["layout.raw"], "vault")
        self.assertEqual(values["layout"]["inbox"], "inbox")
        self.assertEqual(origins["layout.inbox"], "padrão")
        self.assertEqual(origins["language"], "vault")


class ValidateInitArgsTest(unittest.TestCase):
    def setUp(self):
        self.validate = fn("validate_init_args")

    def test_files_inside_the_vault_is_rejected(self):
        """SPEC-0017:UT-02"""
        for files in ("/data/Vault/files", "/data/Vault/a/b"):
            with self.subTest(files=files):
                self.assertEqual(self.validate("/data/Vault", files, "local"), "files precisa ficar fora do vault")

    def test_provider_outside_the_list_is_rejected_with_the_list(self):
        """SPEC-0017:UT-02"""
        message = self.validate("/data/Vault", "/data/Vault-files", "dropbox")
        self.assertIsNotNone(message)
        self.assertIn("dropbox", message)
        for provider in ("google-drive", "onedrive", "icloud", "local"):
            self.assertIn(provider, message)

    def test_valid_arguments_pass(self):
        """SPEC-0017:UT-02"""
        self.assertEqual(tuple(fn("PROVIDERS")), ("google-drive", "onedrive", "icloud", "local"))
        for provider in ("google-drive", "onedrive", "icloud", "local"):
            with self.subTest(provider=provider):
                # pasta irmã com o mesmo prefixo de texto não está dentro do vault
                self.assertIsNone(self.validate("/data/Vault", "/data/Vault-files", provider))


class BrainConfigWithoutAbsolutePathsTest(unittest.TestCase):
    def test_generated_brain_config_has_no_absolute_path(self):
        """SPEC-0017:UT-03"""
        render, parse = fn("render_brain_config"), fn("parse_yaml")
        contexts = {"college": {"folder": "projects/college", "title": "College"}}
        for vault in ("/Users/x/Library/CloudStorage/GoogleDrive/Vault", "C:\\Users\\x\\OneDrive\\Vault"):
            with self.subTest(vault=vault):
                text = render(vault, layout={"inbox": "Inbox"}, contexts=contexts)
                self.assertNotIn("Users", text)
                data = parse(text)
                self.assertEqual(str(data["version"]), "1")
                self.assertEqual(data["layout"]["inbox"], "Inbox")
                self.assertEqual(data["contexts"]["college"]["folder"], "projects/college")
                absolute = [(path, value) for path, value in leaves(data)
                            if isinstance(value, str) and ABSOLUTE.match(value)]
                self.assertEqual(absolute, [])


SAMPLE = """# brain-config de exemplo
version: 1
language: auto   # idioma do conteúdo
layout:
  inbox: Inbox
  index: index.md
para: {projects: projects, areas: Areas}
contexts:
  college: {folder: projects/college, title: College}
  work:
    folder: areas/work
    title: "Work: Main"   # aspas por causa do ': '
processors: {}
tags: [a, b]
steps:
  - one
  - "two: three"
url: https://example.com/a?b=c
note: 'it''s'
hash: "a # b"
"""

EXPECTED = {
    "version": "1",
    "language": "auto",
    "layout": {"inbox": "Inbox", "index": "index.md"},
    "para": {"projects": "projects", "areas": "Areas"},
    "contexts": {
        "college": {"folder": "projects/college", "title": "College"},
        "work": {"folder": "areas/work", "title": "Work: Main"},
    },
    "processors": {},
    "tags": ["a", "b"],
    "steps": ["one", "two: three"],
    "url": "https://example.com/a?b=c",
    "note": "it's",
    "hash": "a # b",
}


class YamlTest(unittest.TestCase):
    def test_parser_reads_the_supported_subset(self):
        """SPEC-0017:UT-04"""
        data = fn("parse_yaml")(SAMPLE)
        self.assertEqual(str(data.pop("version")), "1")
        expected = dict(EXPECTED)
        expected.pop("version")
        self.assertEqual(data, expected)

    def test_writer_round_trip_preserves_the_data(self):
        """SPEC-0017:UT-04"""
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        tricky = dict(EXPECTED, version="1", dash="-x", empty_list=[], quote='say "hi"', colon="a: b")
        for data in (EXPECTED, tricky):
            with self.subTest(keys=sorted(data)):
                text = dump(data)
                self.assertIsInstance(text, str)
                self.assertEqual(parse(text), data)
                self.assertEqual(parse(dump(parse(text))), data)


if __name__ == "__main__":
    unittest.main()
