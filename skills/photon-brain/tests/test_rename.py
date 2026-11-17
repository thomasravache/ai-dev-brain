"""photon-brain com o nome novo: configuração local com leitura dupla, textos e backups (SPEC-0069: UT-01 a UT-09,
IT-01 e IT-02; ADR-0020).

Contrato (seção 6 da spec) que os testes fixam:
    local_config_path(config_home=None) -> Path (leitura, primeiro que existir):
        config_home | $BRAIN_CONFIG_HOME -> DIR/config.yml (sem reserva)
        ~/.config/photon-brain/config.yml
        ~/.config/<antigo>/config.yml (reserva até a SPEC-0073)
        nenhum -> ~/.config/photon-brain/config.yml
    local_config_write_path(config_home=None) -> Path (gravação): DIR/config.yml da sobrescrita, senão sempre
        ~/.config/photon-brain/config.yml; a pasta antiga nunca é gravada, movida nem apagada.
    NOT_CONFIGURED: "photon-brain não configurado nesta máquina — rode init (ou init --join)"
    --version: "photon-brain <BRAIN_VERSION>"; --help, cabeçalho do config.yml local e assets/brain-config.yml dizem
        photon-brain.
    doctor (texto e --json, mesmo formato e exit code):
        só a antiga -> AVISO "configuração no caminho antigo ~/.config/<antigo> — copie com: mkdir -p
            ~/.config/photon-brain && cp -p ~/.config/<antigo>/config.yml ~/.config/photon-brain/"
        as duas     -> AVISO "~/.config/<antigo> é ignorada (vale ~/.config/photon-brain) — pode apagá-la"
        sobrescrita -> nenhum aviso de caminho antigo.
      O texto do contrato tem " — " no meio; os testes conferem "<item> — <detalhe>" de cada linha AVISO, então
      vale tanto o texto inteiro no detalhe quanto dividido entre item e detalhe.
    backup_name -> "photon-brain-AAAA-MM-DD-HHMMSS[-files].zip"; BACKUP_NAME_RE, rotação e restore aceitam também
        o prefixo antigo; a retenção conta os dois prefixos juntos (cada tipo, com e sem -files, à parte).

Isolamento: HOME e XDG_CONFIG_HOME temporários (brain_support.Sandbox); nos casos da pasta padrão, sem
BRAIN_CONFIG_HOME (Sandbox.run_default, ou os.environ trocado só durante a chamada em processo). O nome antigo está
só em OLD_CONFIG_DIR (brain_support). A "máquina da versão anterior" é montada com o init gravando via
BRAIN_CONFIG_HOME=<HOME>/.config/<antigo>, que é onde a versão anterior gravava por padrão.
"""
import datetime as dt
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from brain_support import (
    NEW_CONFIG_DIR,
    NOT_CONFIGURED,
    OLD_CONFIG_DIR,
    SKILL,
    Sandbox,
    brain,
    doctor_lines,
    fn,
    output,
    snapshot,
)
from test_backup import MANIFEST, make_backup_zip, stamp

SPEC = "SPEC-0069"
OLD_PREFIX = OLD_CONFIG_DIR  # o prefixo antigo dos backups é o mesmo nome
NEW_PREFIX = NEW_CONFIG_DIR
OLD_COPY = (f"configuração no caminho antigo ~/.config/{OLD_CONFIG_DIR} — copie com: mkdir -p ~/.config/{NEW_CONFIG_DIR}"
            f" && cp -p ~/.config/{OLD_CONFIG_DIR}/config.yml ~/.config/{NEW_CONFIG_DIR}/")
OLD_IGNORED = f"~/.config/{OLD_CONFIG_DIR} é ignorada (vale ~/.config/{NEW_CONFIG_DIR}) — pode apagá-la"
NOTE = "projects/college/Aula 1.md"
NOTE_TEXT = "# Aula 1\n\nintegrais por partes\n"


def joined(rows) -> list:
    """"<status> <item> — <detalhe>" de cada (status, item, detalhe)."""
    return [f"{status} {item} — {detail}" for status, item, detail in rows]


def json_rows(text: str) -> list:
    return [(i["status"], i["item"], i["detail"]) for i in json.loads(text)["items"]]


class RenameCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.old = self.box.default_dir(OLD_CONFIG_DIR)
        self.new = self.box.default_dir(NEW_CONFIG_DIR)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))

    def old_machine(self):
        """Máquina configurada pela versão anterior: config.yml só em ~/.config/<antigo>, vault real com uma nota."""
        self.box.vault.mkdir(parents=True)
        out = self.box.init("--context", "college=projects/college:College", config_home=self.old)
        self.assertExit(out, 0)
        self.assertTrue((self.old / "config.yml").is_file(), "fixture: init não gravou a configuração antiga")
        self.assertFalse(self.new.exists(), "fixture: a pasta nova não deveria existir")
        path = self.box.vault / NOTE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(NOTE_TEXT, encoding="utf-8")
        return self.old / "config.yml"

    def default_env(self, **extra) -> dict:
        """os.environ do teste em processo: HOME e XDG temporários, sem BRAIN_CONFIG_HOME (salvo `extra`)."""
        env = {k: v for k, v in os.environ.items() if k != "BRAIN_CONFIG_HOME"}
        env.update(HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"), **extra)
        return env

    def resolve(self, config_home=None, **extra):
        read, write = fn("local_config_path", SPEC), fn("local_config_write_path", SPEC)
        with mock.patch.dict(os.environ, self.default_env(**extra), clear=True):
            return read(config_home), write(config_home)

    @staticmethod
    def put(folder: Path, text="vault: /x\n") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.yml").write_text(text, encoding="utf-8")
        return folder / "config.yml"


# ---------------------------------------------------------------- resolução (UT-01, UT-02, UT-04)

class ResolutionTest(RenameCase):
    def test_reads_the_old_folder_alone_and_the_new_one_when_both_exist(self):
        """SPEC-0069:UT-01"""
        old = self.put(self.old)
        self.assertEqual(self.resolve()[0], old, "só a antiga: a leitura usa a antiga como reserva")
        new = self.put(self.new)
        self.assertEqual(self.resolve()[0], new, "as duas: vale a nova")

    def test_without_any_folder_read_and_write_point_to_the_new_folder(self):
        """SPEC-0069:UT-02"""
        expected = self.box.home / ".config" / NEW_CONFIG_DIR / "config.yml"
        self.assertEqual(self.resolve(), (expected, expected))

    def test_write_path_is_always_the_new_folder_even_with_only_the_old_one(self):
        """SPEC-0069:UT-03 (resolução da gravação)"""
        self.put(self.old)
        read, write = self.resolve()
        self.assertEqual(read, self.old / "config.yml")
        self.assertEqual(write, self.new / "config.yml", "a gravação nunca vai para a pasta antiga")

    def test_override_uses_only_its_folder_without_fallback(self):
        """SPEC-0069:UT-04"""
        self.put(self.old)
        self.put(self.new)
        override = self.box.root / "override"
        expected = override / "config.yml"
        with self.subTest(via="BRAIN_CONFIG_HOME"):
            self.assertEqual(self.resolve(BRAIN_CONFIG_HOME=str(override)), (expected, expected),
                             "sobrescrita sem config.yml não cai na reserva")
        with self.subTest(via="config_home"):
            self.assertEqual(self.resolve(config_home=override), (expected, expected))
        with self.subTest(via="config_home vence BRAIN_CONFIG_HOME"):
            other = self.box.root / "other"
            self.assertEqual(self.resolve(config_home=override, BRAIN_CONFIG_HOME=str(other)), (expected, expected))


# ---------------------------------------------------------------- gravação (UT-03, UT-04)

class WriteTest(RenameCase):
    def test_backup_target_add_with_only_the_old_folder_writes_the_full_config_in_the_new_one(self):
        """SPEC-0069:UT-03"""
        old = self.old_machine()
        before = old.read_bytes()
        target = self.box.root / "backups-a"
        target.mkdir()
        out = self.box.run_default("backup", "target", "add", target)
        self.assertExit(out, 0)
        new = self.new / "config.yml"
        self.assertTrue(new.is_file(), f"a gravação não foi para {new}: {output(out)}")
        self.assertEqual(old.read_bytes(), before, "a pasta antiga fica idêntica byte a byte")
        parse = fn("parse_yaml")
        previous, written = parse(before.decode("utf-8")), parse(new.read_text(encoding="utf-8"))
        for key in ("vault", "files", "provider"):
            self.assertEqual(written.get(key), previous.get(key), f"configuração completa: {key}")
        self.assertEqual(written.get("backup_targets"), [str(target)])
        self.assertTrue(new.read_text(encoding="utf-8").startswith(f"# {NEW_CONFIG_DIR}"), "cabeçalho novo")
        data = json.loads(self.box.run_default("config", "--json").stdout)
        self.assertEqual(data["values"]["backup_targets"], [str(target)], "depois da gravação vale a nova")

    def test_init_join_with_only_the_old_folder_keeps_its_backup_targets_in_the_new_one(self):
        """SPEC-0069:UT-03"""
        old = self.old_machine()
        target = self.box.root / "backups-a"
        target.mkdir()
        self.assertExit(self.box.run("backup", "target", "add", target, config_home=self.old), 0)
        before = old.read_bytes()
        out = self.box.run_default("init", "--join", "--vault", self.box.vault, "--files", self.box.files,
                                   "--provider", "local")
        self.assertExit(out, 0)
        new = self.new / "config.yml"
        self.assertTrue(new.is_file(), output(out))
        self.assertEqual(old.read_bytes(), before, "a pasta antiga fica idêntica byte a byte")
        written = fn("parse_yaml")(new.read_text(encoding="utf-8"))
        self.assertEqual(written.get("provider"), "local", "a mudança do comando entra")
        self.assertEqual(written.get("backup_targets"), [str(target)], "o resto da configuração vem da antiga")

    def test_override_is_the_only_folder_read_and_written_and_doctor_has_no_old_path_warning(self):
        """SPEC-0069:UT-04"""
        self.old_machine()
        override = self.box.root / "override"
        shutil.copytree(self.old, override)
        shutil.copytree(self.old, self.new)
        defaults = {name: snapshot(self.box.home / ".config" / name) for name in (OLD_CONFIG_DIR, NEW_CONFIG_DIR)}
        target = self.box.root / "backups-a"
        target.mkdir()
        self.assertExit(self.box.run("backup", "target", "add", target, config_home=override), 0)
        written = fn("parse_yaml")((override / "config.yml").read_text(encoding="utf-8"))
        self.assertEqual(written.get("backup_targets"), [str(target)])
        for name, state in defaults.items():
            self.assertEqual(snapshot(self.box.home / ".config" / name), state, f"{name} não muda com a sobrescrita")
        text = self.box.run("doctor", config_home=override)
        js = self.box.run("doctor", "--json", config_home=override)
        for out in (text, js):
            self.assertNotIn(OLD_CONFIG_DIR, output(out), "nenhum aviso de caminho antigo com a sobrescrita")
            self.assertNotIn("caminho antigo", output(out))
        rows = json_rows(js.stdout)
        self.assertIn(("OK", "configuração local", str(override / "config.yml")), rows)


# ---------------------------------------------------------------- doctor (UT-05)

class DoctorTest(RenameCase):
    def baseline(self):
        """O mesmo doctor com BRAIN_CONFIG_HOME apontando para a pasta antiga: exit code e linhas de hoje."""
        text = self.box.run("doctor", config_home=self.old)
        js = self.box.run("doctor", "--json", config_home=self.old)
        return text, js

    def check_format(self, text, js, base_text, base_js, warning, path):
        self.assertEqual(text.returncode, base_text.returncode, "exit code sem mudança")
        self.assertEqual(js.returncode, base_js.returncode, "exit code sem mudança (--json)")
        self.assertNotIn("Traceback", output(text) + output(js))
        text_rows = doctor_lines(text.stdout)
        warnings = [line for line in joined(text_rows) if line.startswith("AVISO ") and warning in line]
        self.assertEqual(len(warnings), 1, f"um AVISO com {warning!r}:\n{text.stdout}")
        self.assertRegex(text.stdout, r"(?m)^\d+ erro\(s\), \d+ aviso\(s\)$", "linha de totais igual")

        data = json.loads(js.stdout)
        base = json.loads(base_js.stdout)
        self.assertEqual(set(data), set(base), "chaves do --json iguais")
        self.assertEqual(data["ok"], base["ok"])
        for item in data["items"]:
            self.assertEqual(set(item), {"status", "item", "detail"}, item)
        rows = json_rows(js.stdout)
        self.assertEqual(len([line for line in joined(rows) if line.startswith("AVISO ") and warning in line]), 1,
                         f"um AVISO com {warning!r} no --json: {rows}")
        self.assertIn(("OK", "configuração local", str(path)), rows, "a linha de hoje mostra o caminho lido")
        kept = [row for row in json_rows(base_js.stdout) if row[1] != "configuração local"]
        for row in kept:
            self.assertIn(row, rows, "as outras linhas do doctor não mudam")
        return rows

    def test_doctor_warns_with_the_copy_command_and_then_that_the_old_folder_is_ignored(self):
        """SPEC-0069:UT-05"""
        self.old_machine()
        base_text, base_js = self.baseline()
        with self.subTest(case="só a antiga"):
            text, js = self.box.run_default("doctor"), self.box.run_default("doctor", "--json")
            rows = self.check_format(text, js, base_text, base_js, OLD_COPY, self.old / "config.yml")
            self.assertIn("cp -p", OLD_COPY)
            self.assertFalse([r for r in joined(rows) if OLD_IGNORED in r], "sem aviso de pasta ignorada")
        shutil.copytree(self.old, self.new)
        with self.subTest(case="as duas"):
            text, js = self.box.run_default("doctor"), self.box.run_default("doctor", "--json")
            rows = self.check_format(text, js, base_text, base_js, OLD_IGNORED, self.new / "config.yml")
            self.assertFalse([r for r in joined(rows) if OLD_COPY in r], "sem o comando de cópia")
        self.assertFalse((self.old / "config.yml.tmp").exists())
        self.assertEqual(sorted(p.name for p in self.old.iterdir()), ["config.yml"], "a antiga não é tocada")


# ---------------------------------------------------------------- textos (UT-06)

class TextsTest(RenameCase):
    def test_version_help_not_configured_init_header_and_asset_say_photon_brain(self):
        """SPEC-0069:UT-06"""
        out = self.box.run_default("--version")
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), f"{NEW_CONFIG_DIR} {brain().BRAIN_VERSION}")

        out = self.box.run_default("--help")
        self.assertExit(out, 0)
        self.assertIn(NEW_CONFIG_DIR, out.stdout)
        self.assertNotIn(OLD_CONFIG_DIR, out.stdout)

        for args in (("config",), ("search", "aula")):
            with self.subTest(not_configured=args):
                out = self.box.run_default(*args)
                self.assertExit(out, 3)
                self.assertIn(NOT_CONFIGURED, output(out))
                self.assertNotIn(OLD_CONFIG_DIR, output(out))

        self.box.vault.mkdir(parents=True)
        out = self.box.run_default("init", "--vault", self.box.vault, "--files", self.box.files,
                                   "--provider", "local")
        self.assertExit(out, 0)
        self.assertNotIn(OLD_CONFIG_DIR, output(out))
        local = (self.new / "config.yml").read_text(encoding="utf-8")
        self.assertTrue(local.startswith(f"# {NEW_CONFIG_DIR}"), local.splitlines()[:1])
        self.assertNotIn(OLD_CONFIG_DIR, local)
        out = self.box.run_default("config")
        self.assertExit(out, 0)
        self.assertIn(f"{NEW_CONFIG_DIR} {brain().BRAIN_VERSION}", out.stdout)
        self.assertNotIn(OLD_CONFIG_DIR, output(out))

        asset = (SKILL / "assets" / "brain-config.yml").read_text(encoding="utf-8")
        self.assertTrue(asset.startswith(f"# {NEW_CONFIG_DIR}"), asset.splitlines()[:1])
        shared = (self.box.vault / "brain-config.yml").read_text(encoding="utf-8")
        self.assertTrue(shared.startswith(f"# {NEW_CONFIG_DIR}"), "vault novo recebe o cabeçalho novo")


# ---------------------------------------------------------------- backups (UT-07 a UT-09)

class BackupNamesTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_backup_name_uses_the_new_prefix(self):
        """SPEC-0069:UT-07"""
        backup_name = fn("backup_name", SPEC)
        clock = lambda: dt.datetime(2026, 11, 17, 9, 8, 7)
        self.assertEqual(backup_name(with_files=False, clock=clock), f"{NEW_PREFIX}-2026-11-17-090807.zip")
        self.assertEqual(backup_name(with_files=True, clock=clock), f"{NEW_PREFIX}-2026-11-17-090807-files.zip")

    def test_name_pattern_accepts_both_prefixes_and_nothing_else(self):
        """SPEC-0069:UT-08"""
        pattern = brain().BACKUP_NAME_RE
        for name in (f"{NEW_PREFIX}-2026-11-17-090807.zip", f"{OLD_PREFIX}-2026-11-17-090807.zip",
                     f"{NEW_PREFIX}-2026-11-17-090807-files.zip", f"{OLD_PREFIX}-2026-11-17-090807-files.zip"):
            self.assertTrue(pattern.match(name), name)
        for name in ("notas.zip", f"{NEW_PREFIX}-x.zip", "other-brain-2026-11-17-090807.zip",
                     f"{NEW_PREFIX}-2026-11-17-090807.zip.partial", f"x{OLD_PREFIX}-2026-11-17-090807.zip"):
            self.assertFalse(pattern.match(name), name)

    def test_rotation_counts_both_prefixes_together_by_the_date_of_the_name(self):
        """SPEC-0069:UT-08"""
        rotate_backups, backup_names = fn("rotate_backups", SPEC), fn("backup_names", SPEC)
        day = lambda d: dt.datetime(2026, 11, d, 8, 0, 0)
        plain = [stamp(day(d), prefix=OLD_PREFIX if d % 2 else NEW_PREFIX) for d in range(1, 7)]  # 1..6, alternados
        with_files = [stamp(day(d), "-files", prefix=OLD_PREFIX if d % 2 else NEW_PREFIX) for d in range(7, 11)]
        aliens = ["notas.zip", f"{OLD_PREFIX}-x.zip", f"{NEW_PREFIX}-x.zip", "other-brain-2026-11-01-080000.zip",
                  stamp(day(11)) + ".partial"]
        for name in plain + with_files + aliens:
            (self.folder / name).write_bytes(b"conteudo " + name.encode())

        newest_first = list(reversed(plain + with_files))
        self.assertEqual(backup_names(self.folder), newest_first, "os dois prefixos, do mais novo ao mais velho")

        removed = rotate_backups(self.folder, keep=3)
        self.assertEqual(sorted(removed), sorted(plain[:3] + with_files[:1]),
                         "saem os mais velhos pela data, de qualquer prefixo, cada tipo à parte")
        left = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(left, sorted(plain[3:] + with_files[1:] + aliens))
        for name in aliens:
            self.assertEqual((self.folder / name).read_bytes(), b"conteudo " + name.encode(), name)


class RestoreOldBackupTest(RenameCase):
    def test_restore_reads_a_backup_with_the_old_prefix(self):
        """SPEC-0069:UT-09"""
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init("--context", "college=projects/college:College"), 0)
        note = self.box.vault / NOTE
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(NOTE_TEXT, encoding="utf-8")
        dest = self.box.root / "backups"
        dest.mkdir()
        made = self.box.run("backup", "--dest", dest, "--json")
        self.assertExit(made, 0)
        name = json.loads(made.stdout)["name"]
        stamp_part = re.search(r"\d{4}-\d{2}-\d{2}-\d{6}", name).group(0)
        old_zip = dest / f"{OLD_PREFIX}-{stamp_part}.zip"
        (dest / name).rename(old_zip)
        with zipfile.ZipFile(old_zip) as zf:
            self.assertIn(MANIFEST, zf.namelist(), "fixture: zip do backup real")
        note.write_text("# Aula 1\n\nmudada depois do backup\n", encoding="utf-8")

        out = self.box.run("restore", NOTE, "--from", old_zip)
        self.assertExit(out, 0)
        restored = [p for p in note.parent.iterdir() if p.name.startswith("Aula 1 (restaurado ")]
        self.assertEqual(len(restored), 1, sorted(p.name for p in note.parent.iterdir()))
        self.assertEqual(restored[0].read_text(encoding="utf-8"), NOTE_TEXT)

        out_dir = self.box.root / "restaurado"
        self.assertExit(self.box.run("restore", "--from", old_zip, "--to", out_dir), 0)
        self.assertEqual((out_dir / "vault" / NOTE).read_text(encoding="utf-8"), NOTE_TEXT)

        verify = self.box.run("backup", "verify", old_zip)
        self.assertExit(verify, 0)

    def test_backup_list_shows_old_and_new_prefixes_from_the_newest(self):
        """SPEC-0069:UT-09"""
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(), 0)
        dest = self.box.root / "backups"
        dest.mkdir()
        self.assertExit(self.box.run("backup", "target", "add", dest), 0)
        old = make_backup_zip(dest / stamp(dt.datetime(2026, 11, 1, 8, 0, 0), prefix=OLD_PREFIX),
                              {"vault/velha.md": b"# velha\n"})
        new = make_backup_zip(dest / stamp(dt.datetime(2026, 11, 2, 8, 0, 0)), {"vault/nova.md": b"# nova\n"})
        out = self.box.run("backup", "list", "--json")
        self.assertExit(out, 0)
        names = [b["name"] for t in json.loads(out.stdout)["targets"] for b in t["backups"]]
        self.assertEqual(names, [new.name, old.name])


# ---------------------------------------------------------------- integração (IT-01, IT-02)

class OldMachineCliTest(RenameCase):
    def test_machine_configured_by_the_previous_version_works_without_action(self):
        """SPEC-0069:IT-01"""
        old = self.old_machine()
        before = old.read_bytes()

        out = self.box.run_default("search", "integrais", "--json")
        self.assertExit(out, 0)
        self.assertIn(NOTE, [r["path"] for r in json.loads(out.stdout)["results"]])

        out = self.box.run_default("context", "integrais", "--json")
        self.assertExit(out, 0)
        self.assertIn("integrais por partes", out.stdout)

        base = self.box.run("doctor", config_home=self.old)
        out = self.box.run_default("doctor")
        self.assertEqual(out.returncode, base.returncode, output(out))
        self.assertTrue([line for line in joined(doctor_lines(out.stdout)) if OLD_COPY in line], out.stdout)

        dest = self.box.root / "backups"
        dest.mkdir()
        out = self.box.run_default("backup", "--dest", dest, "--json")
        self.assertExit(out, 0)
        name = json.loads(out.stdout)["name"]
        self.assertRegex(name, rf"^{NEW_PREFIX}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}\.zip$")
        self.assertEqual(sorted(p.name for p in dest.iterdir()), [name])

        self.assertEqual(old.read_bytes(), before, "a configuração antiga nunca é gravada")
        self.assertFalse(self.new.exists(), "comandos que não gravam a configuração não criam a pasta nova")


class NewMachineCliTest(RenameCase):
    def test_init_on_a_machine_without_configuration_creates_only_the_new_folder(self):
        """SPEC-0069:IT-02"""
        out = self.box.run_default("doctor")
        self.assertExit(out, 3)
        self.assertIn(NOT_CONFIGURED, output(out))

        self.box.vault.mkdir(parents=True)
        out = self.box.run_default("init", "--vault", self.box.vault, "--files", self.box.files,
                                   "--provider", "google-drive")
        self.assertExit(out, 0)
        local = self.new / "config.yml"
        self.assertIn(f"Configuração local gravada em {local}", out.stdout)
        self.assertEqual(sorted(p.name for p in (self.box.home / ".config").iterdir()), [NEW_CONFIG_DIR])
        self.assertEqual(sorted(p.name for p in self.new.iterdir()), ["config.yml"])
        self.assertFalse(self.old.exists())
        self.assertEqual(self.box.config_json(config_home=self.new)["values"]["vault"], str(self.box.vault))


if __name__ == "__main__":
    unittest.main()
