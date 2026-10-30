"""Vault recém-criado pelo app do Obsidian (só `.obsidian/`) recebe a estrutura padrão no init (SPEC-0025: UT-01, IT-01).

Contrato conferido:
    is_empty_vault(folder: Path) -> bool   função pura a extrair de brain.py (hoje a checagem é inline em
                                           cmd_init: `any(e.name not in OS_METADATA for e in vault.iterdir())`).
                                           True quando, fora de OS_METADATA, o único conteúdo é `.obsidian/`
                                           (ou não há nada); qualquer outro arquivo ou pasta -> False.
    init sem --adopt                       pasta só com `.obsidian/` (+ .DS_Store) -> exit 0, estrutura padrão
                                           completa criada e nada dentro de `.obsidian/` muda (conteúdo e mtime).

A recusa de uma pasta com notas ("vault não está vazio — use --adopt") continua coberta pelo SPEC-0017:IT-09
(test_amendment_v2.NotEmptyWithoutAdoptTest) e não é repetida aqui.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import fn, output, snapshot
from test_cli import OLD_MTIME, STRUCTURE_DIRS, STRUCTURE_FILES, CliTestCase

SPEC = "SPEC-0025"
APP_JSON = '{"alwaysUpdateLinks": true}\n'


def obsidian_folder(vault: Path) -> Path:
    """`.obsidian/` como o app cria, com arquivos dentro e mtimes antigos (mudança = mtime novo)."""
    config = vault / ".obsidian"
    (config / "plugins").mkdir(parents=True)
    (config / "app.json").write_text(APP_JSON, encoding="utf-8")
    (config / "workspace.json").write_text('{"main": {}}\n', encoding="utf-8")
    (config / "plugins" / "list.json").write_text("[]\n", encoding="utf-8")
    for path in sorted(config.rglob("*"), reverse=True) + [config]:
        os.utime(path, (OLD_MTIME, OLD_MTIME))
    return config


class EmptyVaultCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_only_obsidian_and_os_metadata_counts_as_empty_and_a_note_does_not(self):
        """SPEC-0025:UT-01"""
        is_empty_vault = fn("is_empty_vault", SPEC)
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "app.json").write_text(APP_JSON, encoding="utf-8")
        (self.root / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        self.assertTrue(is_empty_vault(self.root), "pasta só com .obsidian/ e .DS_Store deveria contar como vazia")
        (self.root / "nota.md").write_text("# Nota\n", encoding="utf-8")
        self.assertFalse(is_empty_vault(self.root), "pasta com nota.md não pode contar como vazia")


class ObsidianVaultInitTest(CliTestCase):
    def test_init_in_a_vault_created_by_obsidian_creates_the_structure_and_keeps_obsidian(self):
        """SPEC-0025:IT-01"""
        vault = self.box.vault
        vault.mkdir(parents=True)
        config = obsidian_folder(vault)
        (vault / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        before = snapshot(config)
        config_mtime = config.stat().st_mtime_ns

        out = self.box.init(provider="icloud")
        self.assertExit(out, 0)
        self.assertNotIn("use --adopt", output(out))
        self.assertIn(f"Vault criado em {vault}", out.stdout)
        for name in STRUCTURE_DIRS:
            self.assertTrue((vault / name).is_dir(), name)
        for name in STRUCTURE_FILES:
            self.assertTrue((vault / name).is_file(), name)
        self.assertTrue(list((vault / "templates").glob("*.md")), "templates/ sem modelos")
        self.assertTrue(self.box.files.is_dir(), "init não criou a pasta files")
        self.assertTrue((self.box.config_home / "config.yml").is_file(), "init não gravou a configuração local")

        self.assertEqual(snapshot(config), before, "init alterou algo dentro de .obsidian/")
        self.assertEqual(config.stat().st_mtime_ns, config_mtime, "init mexeu na pasta .obsidian/")
        self.assertEqual((config / "app.json").read_text(encoding="utf-8"), APP_JSON)


if __name__ == "__main__":
    unittest.main()
