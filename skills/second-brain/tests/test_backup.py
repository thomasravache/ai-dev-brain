"""Unidades do backup do vault: configuração, nome, rotação, manifesto, verificação e entradas perigosas
(SPEC-0051: UT-01 a UT-05).

Funções de scripts/brain.py que os testes chamam (ausente = falha pelo motivo certo):
    read_config(config_home) -> values["backup"] = {"keep": int, "warn_days": int, "with_files": bool}; valor
        inválido usa o padrão (10, 7, false) e entra em config["warnings"] com a chave citada ("backup.keep",
        "backup.warn_days"), como inbox_stale_days.
    backup_name(with_files=False, clock=None) -> "second-brain-AAAA-MM-DD-HHMMSS[-files].zip"
        (clock: função sem argumento que devolve datetime, como em capture_name; None = datetime.now).
    rotate_backups(folder, keep=N) -> lista dos nomes removidos (ADR-0015): só nomes do padrão, cada tipo
        (com e sem -files) contado separado, os mais velhos além de keep saem; o resto da pasta fica.
    build_manifest(vault, files=None) -> {"brain_version", "created", "with_files", "entries": {"vault/<rel>":
        sha256, "files/<rel>": sha256}}; with_files = files informado.
    verify_backup(zip_path) -> (ok: bool, detalhe: str); detalhe traz o motivo quando ok é False.
    safe_entry(nome) -> bool: False para entrada com ".." ou caminho absoluto.

Os zips dos casos inválidos são montados à mão aqui (make_backup_zip), sem usar o brain.py.
"""
import datetime as dt
import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from brain_support import Sandbox, brain, fn

SPEC = "SPEC-0051"
MANIFEST = "brain-backup.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_backup_zip(path, entries, with_files=False, manifest_entries=None, contents=None):
    """Zip no formato do contrato: as entradas (caminho no zip -> bytes) e brain-backup.json com o sha256 de cada
    uma. `manifest_entries` substitui o manifesto calculado; `contents` substitui o que é gravado (entrada
    alterada ou faltando). Usa ZipInfo direto para manter nomes com ".." ou "/" no começo."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"brain_version": "teste", "created": "2026-11-02T08:00:00", "with_files": with_files,
                "entries": manifest_entries if manifest_entries is not None
                else {name: sha(data) for name, data in entries.items()}}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (contents if contents is not None else entries).items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 11, 2, 8, 0, 0)), data)
        zf.writestr(MANIFEST, json.dumps(manifest))
    return path


def stamp(moment: dt.datetime, suffix="") -> str:
    return f"second-brain-{moment.strftime('%Y-%m-%d-%H%M%S')}{suffix}.zip"


class BackupSettingsTest(unittest.TestCase):
    """SPEC-0051:UT-01"""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.new_vault()
        self.shared = self.box.vault / "brain-config.yml"
        self.original = self.shared.read_text(encoding="utf-8")

    def settings(self, block):
        self.shared.write_text(self.original + block, encoding="utf-8")
        config = fn("read_config")(self.box.config_home)
        return config["values"].get("backup"), config.get("warnings", [])

    def test_missing_valid_and_invalid_backup_settings(self):
        """SPEC-0051:UT-01"""
        defaults = {"keep": 10, "warn_days": 7, "with_files": False}
        backup, warnings = self.settings("")
        self.assertEqual(backup, defaults, "backup ausente = padrão 10/7/false")
        self.assertFalse([w for w in warnings if "backup" in json.dumps(w)], warnings)

        backup, warnings = self.settings("backup:\n  keep: 3\n  warn_days: 0\n  with_files: true\n")
        self.assertEqual(backup, {"keep": 3, "warn_days": 0, "with_files": True})
        self.assertFalse([w for w in warnings if "backup" in json.dumps(w)], warnings)

        for block, key in (("backup:\n  keep: 0\n", "backup.keep"),
                           ("backup:\n  keep: x\n", "backup.keep"),
                           ("backup:\n  warn_days: -1\n", "backup.warn_days")):
            with self.subTest(block=block):
                backup, warnings = self.settings(block)
                self.assertEqual(backup, defaults, f"inválido usa o padrão: {block!r}")
                cited = [w for w in warnings if key in f"{w.get('key', '')} {w.get('message', '')}"]
                self.assertTrue(cited, f"aviso que cita {key}: {warnings}")


class BackupNameAndRotationTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_backup_name_follows_the_pattern(self):
        """SPEC-0051:UT-02"""
        backup_name = fn("backup_name", SPEC)
        clock = lambda: dt.datetime(2026, 11, 2, 8, 5, 9)
        self.assertEqual(backup_name(with_files=False, clock=clock), "second-brain-2026-11-02-080509.zip")
        self.assertEqual(backup_name(with_files=True, clock=clock), "second-brain-2026-11-02-080509-files.zip")

    def test_rotation_removes_only_the_oldest_pattern_names_beyond_keep(self):
        """SPEC-0051:UT-02"""
        rotate_backups = fn("rotate_backups", SPEC)
        plain = [stamp(dt.datetime(2026, 11, day, 8, 0, 0)) for day in range(1, 13)]
        others = [stamp(dt.datetime(2026, 11, 12, 8, 0, 0), "-files"), "notas.zip", "second-brain-x.zip",
                  stamp(dt.datetime(2026, 11, 13, 8, 0, 0)) + ".partial"]
        for name in plain + others:
            (self.folder / name).write_bytes(b"conteudo " + name.encode())
        removed = rotate_backups(self.folder, keep=10)
        self.assertEqual(sorted(removed), sorted(plain[:2]), "saem só os dois mais velhos sem -files")
        left = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(left, sorted(plain[2:] + others))
        for name in others:
            self.assertEqual((self.folder / name).read_bytes(), b"conteudo " + name.encode(), name)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.vault = self.root / "Vault"
        self.data = {"a.md": b"# A\n", "sub/b.md": "# B ç\n".encode(), ".obsidian/app.json": b"{}"}
        for rel, data in self.data.items():
            (self.vault / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.vault / rel).write_bytes(data)

    def test_manifest_lists_each_vault_file_with_its_sha256(self):
        """SPEC-0051:UT-03"""
        manifest = fn("build_manifest", SPEC)(self.vault)
        self.assertEqual(manifest["entries"], {f"vault/{rel}": sha(data) for rel, data in self.data.items()})
        self.assertIs(manifest["with_files"], False)
        self.assertEqual(manifest["brain_version"], brain().BRAIN_VERSION)
        self.assertTrue(manifest.get("created"), manifest)

    def test_manifest_with_files_adds_files_entries(self):
        """SPEC-0051:UT-03"""
        files = self.root / "Vault-files"
        (files / "college").mkdir(parents=True)
        (files / "college" / "aula.pdf").write_bytes(b"%PDF-1.4 aula")
        manifest = fn("build_manifest", SPEC)(self.vault, files)
        self.assertEqual(manifest["entries"]["files/college/aula.pdf"], sha(b"%PDF-1.4 aula"))
        self.assertIn("vault/a.md", manifest["entries"])
        self.assertIs(manifest["with_files"], True)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.entries = {"vault/a.md": b"# A\n", "vault/sub/b.md": b"# B\n"}

    def test_only_the_intact_zip_passes_and_the_others_bring_the_reason(self):
        """SPEC-0051:UT-04"""
        verify_backup = fn("verify_backup", SPEC)
        intact = make_backup_zip(self.root / "intacto.zip", self.entries)
        altered = make_backup_zip(self.root / "alterado.zip", self.entries,
                                  contents=dict(self.entries, **{"vault/a.md": b"# A mudado\n"}))
        missing = make_backup_zip(self.root / "faltando.zip", self.entries,
                                  contents={"vault/a.md": self.entries["vault/a.md"]})
        truncated = self.root / "truncado.zip"
        truncated.write_bytes(intact.read_bytes()[:-40])

        ok, detail = verify_backup(intact)
        self.assertTrue(ok, detail)
        for path, reason in ((altered, r"(?i)sha256|hash"), (missing, r"(?i)falt|ausente|missing"),
                             (truncated, r"(?i)inv[aá]lid|corromp|invalid|bad zip|truncad")):
            with self.subTest(zip=path.name):
                ok, detail = verify_backup(path)
                self.assertFalse(ok, f"{path.name} não pode passar")
                self.assertRegex(detail, reason)


class SafeEntryTest(unittest.TestCase):
    def test_entries_ending_in_slash_are_not_accepted(self):
        """SPEC-0051:UT-05"""
        safe_entry = fn("safe_entry", SPEC)
        for name in ("vault/", "vault/sub/", "files/"):
            with self.subTest(name=name):
                self.assertFalse(safe_entry(name), name)
        self.assertTrue(safe_entry("vault/sub/a.md"))


    def test_only_entries_without_dotdot_or_absolute_path_are_accepted(self):
        """SPEC-0051:UT-05"""
        safe_entry = fn("safe_entry", SPEC)
        self.assertTrue(safe_entry("vault/a.md"))
        for name in ("vault/../x.md", "/etc/x", "vault/sub/../../x.md"):
            with self.subTest(name=name):
                self.assertFalse(safe_entry(name), name)


if __name__ == "__main__":
    unittest.main()
