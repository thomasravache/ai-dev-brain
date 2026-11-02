"""Integração pela CLI: backup target add, backup, backup list, backup verify, restore e doctor
(SPEC-0051: IT-01 a IT-08).

Cada teste cria o vault com o `brain.py init` real (contexto college) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox); os destinos de backup ficam em <tmp>/backups-*, fora do vault
e da pasta files. Mensagens de erro podem ir para stdout ou stderr.

Saídas que os testes conferem (contrato da seção 6):
    backup target add PASTA -> backup_targets: [PASTA absoluta] em $BRAIN_CONFIG_HOME/config.yml; repetida ->
        "destino já existe", exit 0; dentro do vault ou da pasta files -> exit 2, config.yml igual.
    backup [--dest PASTA ...] [--with-files] --json -> {"name", "entries" (número de entradas do manifesto),
        "targets": [{"path", "status": "ok"|"failed", "detail", "removed": [nomes]}]}; zip
        second-brain-AAAA-MM-DD-HHMMSS[-files].zip com vault/<rel>, files/<rel> e brain-backup.json.
    backup list --json -> {"targets": [{"path", "status": "ok"|"failed", "detail", "backups": [{"name", "created",
        "size", "entries", "with_files"}]}]}, backups do mais novo para o mais velho (hipótese de chaves do
        Test-writer, seguindo o --json do backup).
    backup verify [ZIP] -> "OK <zip> — N entradas" | "ERRO <zip> — <motivo>"; 0, 1 com erro, 2 ZIP inexistente.
    restore NOTA --from ZIP -> "<pasta>/<nome> (restaurado AAAA-MM-DD).md", depois "...)-1.md" (aceita também
        "...) -1.md"); restore --from ZIP --to PASTA -> PASTA/vault/... e PASTA/files/....
    doctor -> "OK|AVISO backup <destino> — ..." e "AVISO backup — nenhum destino configurado (references/backup.md)".

Idades e ordem: vêm do carimbo no nome do zip (determinístico); os testes também ajustam o mtime para a mesma data.
A falha de escrita do IT-03 roda o `main` em processo e troca `write_backup_zip` (a função do brain.py que grava o
conteúdo do zip no `.partial`) por uma que grava meio arquivo e levanta OSError.
"""
import contextlib
import datetime as dt
import errno
import io
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from unittest import mock

from brain_support import brain, doctor_lines, fn, output, snapshot
from test_backup import MANIFEST, make_backup_zip, sha, stamp
from test_store_cli import StoreCliTestCase, today

SPEC = "SPEC-0051"
PATTERN = re.compile(r"^second-brain-\d{4}-\d{2}-\d{2}-\d{6}(-files)?\.zip$")
NOTE_A = "projects/college/Aula 1.md"
NOTE_B = "projects/college/Aula 2.md"


def patterned(folder: Path) -> list:
    return sorted(p.name for p in folder.iterdir() if PATTERN.match(p.name)) if folder.is_dir() else []


def manifest_of(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(MANIFEST))


class BackupCliTestCase(StoreCliTestCase):
    def setUp(self):
        super().setUp()
        self.make_vault()
        self.write(NOTE_A, "# Aula 1\n\nversão do backup\n")
        self.write(NOTE_B, "# Aula 2\n\nnota que será apagada\n")
        self.a = self.box.root / "backups-a"
        self.b = self.box.root / "backups-b"
        self.a.mkdir()
        self.b.mkdir()

    def local_config(self) -> Path:
        return self.box.config_home / "config.yml"

    def targets(self) -> list:
        return fn("parse_yaml")(self.local_config().read_text(encoding="utf-8")).get("backup_targets")

    def add_target(self, folder, code=0):
        out = self.box.run("backup", "target", "add", folder)
        self.assertExit(out, code)
        return out

    def shared_block(self, block):
        path = self.box.vault / "brain-config.yml"
        path.write_text(path.read_text(encoding="utf-8") + block, encoding="utf-8")

    def backup_json(self, *args, code=0):
        return self.json_of("backup", *args, code=code)

    def target_of(self, data, folder):
        found = [t for t in data["targets"] if Path(t["path"]).resolve() == folder.resolve()]
        self.assertEqual(len(found), 1, f"destino {folder} no JSON: {data}")
        return found[0]

    def fake_backup(self, folder, moment, entries=None, suffix=""):
        """Zip válido do padrão com o carimbo de `moment` (mtime ajustado para a mesma data)."""
        path = make_backup_zip(folder / stamp(moment, suffix), entries or {"vault/velha.md": b"# velha\n"},
                               with_files=bool(suffix))
        os.utime(path, (moment.timestamp(), moment.timestamp()))
        return path

    def state(self):
        files = {k: v[0] for k, v in snapshot(self.box.files).items()} if self.box.files.exists() else {}
        return {k: v[0] for k, v in snapshot(self.box.vault).items()}, files


class TargetAddTest(BackupCliTestCase):
    def test_target_add_records_once_reports_repeated_and_refuses_inside_vault_or_files(self):
        """SPEC-0051:IT-01"""
        self.add_target(self.a)
        self.assertEqual(self.targets(), [str(self.a)])
        out = self.add_target(self.a)
        self.assertIn("destino já existe", output(out))
        self.assertEqual(self.targets(), [str(self.a)])
        before = self.local_config().read_bytes()
        self.box.files.mkdir(parents=True, exist_ok=True)
        for inside in (self.box.vault / "backups", self.box.files / "backups"):
            with self.subTest(inside=inside):
                inside.mkdir(parents=True, exist_ok=True)
                self.add_target(inside, code=2)
                self.assertEqual(self.local_config().read_bytes(), before, "configuração local não muda")


class BackupTest(BackupCliTestCase):
    def test_backup_in_two_targets_writes_a_verified_zip_in_each_and_logs(self):
        """SPEC-0051:IT-02"""
        self.add_target(self.a)
        self.add_target(self.b)
        log_before = self.log()
        data = self.backup_json()
        name = data["name"]
        self.assertRegex(name, r"^second-brain-\d{4}-\d{2}-\d{2}-\d{6}\.zip$")
        for folder in (self.a, self.b):
            target = self.target_of(data, folder)
            self.assertEqual(target["status"], "ok", target)
            self.assertEqual(patterned(folder), [name])
            self.assertFalse(list(folder.glob("*.partial")), "nenhum .partial sobra")
            out = self.box.run("backup", "verify", folder / name)
            self.assertExit(out, 0)
            self.assertRegex(out.stdout, rf"(?m)^OK .*{re.escape(name)}")
        manifest = manifest_of(self.a / name)
        self.assertIs(manifest["with_files"], False)
        self.assertEqual(data["entries"], len(manifest["entries"]))
        self.assertIn(f"vault/{NOTE_A}", manifest["entries"])
        self.assertIn("vault/brain-config.yml", manifest["entries"])
        self.assertFalse([e for e in manifest["entries"] if e.startswith("files/")])
        with zipfile.ZipFile(self.a / name) as zf:
            self.assertEqual(zf.read(f"vault/{NOTE_A}"), (self.box.vault / NOTE_A).read_bytes())
        lines = self.new_log_lines(log_before)
        self.assertTrue([line for line in lines if "backup" in line and name in line and "2 destino" in line],
                        f"linha do backup no log.md: {lines}")

    def test_missing_target_fails_and_the_other_still_gets_the_zip(self):
        """SPEC-0051:IT-02"""
        self.add_target(self.a)
        self.add_target(self.b)
        shutil.rmtree(self.b)
        data = self.backup_json(code=1)
        self.assertEqual(self.target_of(data, self.a)["status"], "ok")
        failed = self.target_of(data, self.b)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed.get("detail"), f"motivo da falha: {failed}")
        self.assertEqual(patterned(self.a), [data["name"]])
        self.assertFalse(self.b.exists() and patterned(self.b), "nada no destino que falhou")

    def test_without_any_target_exits_2_pointing_to_the_reference(self):
        """SPEC-0051:IT-02"""
        before = self.state()
        out = self.box.run("backup")
        self.assertExit(out, 2)
        self.assertIn("references/backup.md", output(out))
        self.assertEqual(self.state(), before)

    def test_dest_inside_vault_or_files_exits_2_writing_nothing(self):
        """SPEC-0051:IT-02"""
        self.box.files.mkdir(parents=True, exist_ok=True)
        self.add_target(self.a)
        for inside in (self.box.vault / "backups", self.box.files / "backups"):
            with self.subTest(inside=inside):
                inside.mkdir(parents=True, exist_ok=True)
                before = self.state()
                out = self.box.run("backup", "--dest", inside)
                self.assertExit(out, 2)
                self.assertEqual(self.state(), before, "nada gravado no vault nem em files")
                self.assertEqual(patterned(self.a), [], "--dest substitui os destinos: nada em backups-a")

    def test_with_files_names_the_zip_files_and_adds_files_entries(self):
        """SPEC-0051:IT-02"""
        pdf = self.box.files / "college" / "2026" / "aula.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 aula")
        data = self.backup_json("--dest", self.a, "--with-files")
        self.assertRegex(data["name"], r"^second-brain-\d{4}-\d{2}-\d{2}-\d{6}-files\.zip$")
        manifest = manifest_of(self.a / data["name"])
        self.assertIs(manifest["with_files"], True)
        self.assertEqual(manifest["entries"].get("files/college/2026/aula.pdf"), sha(b"%PDF-1.4 aula"))
        self.assertIn(f"vault/{NOTE_A}", manifest["entries"])


class RotationAndFailureTest(BackupCliTestCase):
    def test_rotation_keeps_ten_pattern_backups_and_the_user_file(self):
        """SPEC-0051:IT-03"""
        self.shared_block("backup:\n  keep: 10\n")
        self.add_target(self.a)
        start = dt.datetime.now().replace(microsecond=0) - dt.timedelta(days=30)
        old = [self.fake_backup(self.a, start + dt.timedelta(days=i)).name for i in range(11)]
        photos = self.a / "fotos.zip"
        photos.write_bytes(b"fotos da pessoa")
        data = self.backup_json()
        new = data["name"]
        left = patterned(self.a)
        self.assertEqual(len(left), 10, left)
        self.assertIn(new, left)
        self.assertEqual(sorted(self.target_of(data, self.a)["removed"]), sorted(old[:2]))
        self.assertEqual(left, sorted(old[2:] + [new]))
        self.assertEqual(photos.read_bytes(), b"fotos da pessoa")

    def test_write_failure_in_the_middle_keeps_previous_backups_and_creates_no_pattern_name(self):
        """SPEC-0051:IT-03"""
        self.add_target(self.a)
        start = dt.datetime.now().replace(microsecond=0) - dt.timedelta(days=3)
        previous = {p.name: p.read_bytes() for p in (self.fake_backup(self.a, start),
                                                     self.fake_backup(self.a, start + dt.timedelta(days=1)))}
        module = brain()
        fn("write_backup_zip", SPEC)

        def failing_write(*args, **kwargs):
            for value in (*args, *kwargs.values()):
                if isinstance(value, (str, Path)) and str(value).endswith(".partial"):
                    Path(value).write_bytes(b"PK\x03\x04 meio zip")
            raise OSError(errno.ENOSPC, "sem espaço (falha simulada)")

        env = {"HOME": str(self.box.home), "BRAIN_CONFIG_HOME": str(self.box.config_home)}
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(module, "write_backup_zip", failing_write), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(["backup", "--json"])
        self.assertEqual(code, 1, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(patterned(self.a), sorted(previous), "nenhum nome do padrão criado")
        for name, data in previous.items():
            self.assertEqual((self.a / name).read_bytes(), data, f"{name} intacto")
        self.assertFalse(list(self.a.glob("*.partial")), "o .partial da falha não fica no destino (ADR-0015)")


class ListAndVerifyTest(BackupCliTestCase):
    def test_list_shows_backups_newest_first_and_the_unreachable_target(self):
        """SPEC-0051:IT-04"""
        self.add_target(self.a)
        self.add_target(self.b)
        shutil.rmtree(self.b)
        older = self.fake_backup(self.a, dt.datetime.now().replace(microsecond=0) - dt.timedelta(days=2))
        newest = self.a / self.backup_json(code=1)["name"]
        data = self.json_of("backup", "list")
        listed = self.target_of(data, self.a)
        self.assertEqual([item["name"] for item in listed["backups"]], [newest.name, older.name])
        for item in listed["backups"]:
            self.assertTrue({"name", "created", "size", "entries", "with_files"} <= set(item), item)
        self.assertEqual(listed["backups"][1]["entries"], 1)
        self.assertEqual(listed["backups"][1]["size"], older.stat().st_size)
        unreachable = self.target_of(data, self.b)
        self.assertTrue(unreachable.get("detail"), f"motivo do destino inacessível: {unreachable}")
        self.assertFalse(unreachable.get("backups"))
        out = self.box.run("backup", "verify")
        self.assertRegex(out.stdout, rf"(?m)^OK .*{re.escape(newest.name)} — \d+ entradas")
        self.assertNotRegex(out.stdout, rf"(?m)^ERRO .*{re.escape(newest.name)}")

    def test_verify_reports_an_altered_zip_and_a_missing_one(self):
        """SPEC-0051:IT-04"""
        name = self.backup_json("--dest", self.a)["name"]
        original = self.a / name
        with zipfile.ZipFile(original) as zf:
            contents = {info.filename: zf.read(info) for info in zf.infolist() if info.filename != MANIFEST}
            manifest = json.loads(zf.read(MANIFEST))
        altered = make_backup_zip(self.box.root / "alterado" / name, contents,
                                  manifest_entries=manifest["entries"],
                                  contents=dict(contents, **{f"vault/{NOTE_A}": b"mudado a mao\n"}))
        out = self.box.run("backup", "verify", altered)
        self.assertExit(out, 1)
        self.assertRegex(out.stdout + out.stderr, rf"(?m)^ERRO .*{re.escape(name)} — \S")
        out = self.box.run("backup", "verify", self.a / "second-brain-2020-01-01-000000.zip")
        self.assertExit(out, 2)


class RestoreNoteTest(BackupCliTestCase):
    def test_restore_writes_a_new_file_next_to_the_note_and_never_overwrites(self):
        """SPEC-0051:IT-05"""
        name = self.backup_json("--dest", self.a)["name"]
        zip_path = self.a / name
        backed_a, backed_b = self.read(NOTE_A), self.read(NOTE_B)
        self.write(NOTE_A, "# Aula 1\n\nversão nova, depois do backup\n")
        (self.box.vault / NOTE_B).unlink()
        current_a = self.read(NOTE_A)
        folder = self.box.vault / "projects" / "college"
        dates = {today()}
        log_before = self.log()
        self.assertExit(self.box.run("restore", NOTE_A, "--from", zip_path), 0)
        self.assertExit(self.box.run("restore", NOTE_B, "--from", zip_path), 0)
        self.assertExit(self.box.run("restore", NOTE_A, "--from", zip_path), 0)
        dates.add(today())
        day = "|".join(dates)
        names = sorted(p.name for p in folder.iterdir())
        first_a = [n for n in names if re.fullmatch(rf"Aula 1 \(restaurado ({day})\)\.md", n)]
        second_a = [n for n in names if re.fullmatch(rf"Aula 1 \(restaurado ({day})\) ?-1\.md", n)]
        restored_b = [n for n in names if re.fullmatch(rf"Aula 2 \(restaurado ({day})\)\.md", n)]
        self.assertEqual((len(first_a), len(second_a), len(restored_b)), (1, 1, 1), names)
        self.assertEqual((folder / first_a[0]).read_text(encoding="utf-8"), backed_a)
        self.assertEqual((folder / second_a[0]).read_text(encoding="utf-8"), backed_a)
        self.assertEqual((folder / restored_b[0]).read_text(encoding="utf-8"), backed_b)
        self.assertEqual(self.read(NOTE_A), current_a, "a nota atual não muda")
        self.assertFalse((self.box.vault / NOTE_B).exists(), "a nota apagada não volta com o nome original")
        lines = [line for line in self.new_log_lines(log_before) if "restore" in line]
        self.assertGreaterEqual(len(lines), 3, f"uma linha de restore por restauração: {lines}")

    def test_restore_of_a_note_outside_the_zip_exits_2_and_a_bad_zip_exits_1(self):
        """SPEC-0051:IT-05"""
        name = self.backup_json("--dest", self.a)["name"]
        before = self.state()
        out = self.box.run("restore", "projects/college/Nao existe.md", "--from", self.a / name)
        self.assertExit(out, 2)
        self.assertEqual(self.state(), before)
        with zipfile.ZipFile(self.a / name) as zf:
            contents = {info.filename: zf.read(info) for info in zf.infolist() if info.filename != MANIFEST}
            manifest = json.loads(zf.read(MANIFEST))
        bad = make_backup_zip(self.box.root / "ruim" / name, contents, manifest_entries=manifest["entries"],
                              contents=dict(contents, **{f"vault/{NOTE_A}": b"alterado\n"}))
        out = self.box.run("restore", NOTE_A, "--from", bad)
        self.assertExit(out, 1)
        self.assertEqual(self.state(), before, "zip que não verifica: nada gravado")


class RestoreAllTest(BackupCliTestCase):
    def files_in(self, folder: Path) -> dict:
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def test_restore_to_a_new_folder_extracts_vault_and_files(self):
        """SPEC-0051:IT-06"""
        pdf = self.box.files / "college" / "2026" / "aula.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 aula")
        name = self.backup_json("--dest", self.a, "--with-files")["name"]
        entries = manifest_of(self.a / name)["entries"]
        out_dir = self.box.root / "restaurado"
        self.assertExit(self.box.run("restore", "--from", self.a / name, "--to", out_dir), 0)
        restored = self.files_in(out_dir)
        self.assertEqual(sorted(restored), sorted(entries), "PASTA tem só vault/ e files/ do backup")
        for rel, digest in entries.items():
            self.assertEqual(sha(restored[rel]), digest, rel)
        self.assertEqual(restored["files/college/2026/aula.pdf"], b"%PDF-1.4 aula")
        self.assertEqual(restored[f"vault/{NOTE_A}"], (self.box.vault / NOTE_A).read_bytes())

    def test_restore_to_a_folder_with_files_or_inside_the_vault_exits_2(self):
        """SPEC-0051:IT-06"""
        name = self.backup_json("--dest", self.a)["name"]
        busy = self.box.root / "ocupada"
        busy.mkdir()
        (busy / "minha.txt").write_text("da pessoa", encoding="utf-8")
        out = self.box.run("restore", "--from", self.a / name, "--to", busy)
        self.assertExit(out, 2)
        self.assertEqual(self.files_in(busy), {"minha.txt": b"da pessoa"})
        before = self.state()
        out = self.box.run("restore", "--from", self.a / name, "--to", self.box.vault / "restaurado")
        self.assertExit(out, 2)
        self.assertEqual(self.state(), before, "nada gravado no vault")


class DangerousEntryTest(BackupCliTestCase):
    def test_restore_refuses_dotdot_and_absolute_entries_writing_nothing(self):
        """SPEC-0051:IT-07"""
        outside = self.box.root / "fora.md"
        for label, entry in (("dotdot", "vault/../fora.md"), ("absoluto", str(outside))):
            with self.subTest(entry=label):
                zip_path = make_backup_zip(self.box.root / f"perigoso-{label}" / stamp(dt.datetime(2026, 11, 2, 8)),
                                           {"vault/a.md": b"# a\n", entry: b"fora do destino\n"})
                out_dir = self.box.root / f"novo-{label}"
                before = self.state()
                out = self.box.run("restore", "--from", zip_path, "--to", out_dir)
                self.assertExit(out, 1)
                self.assertFalse(outside.exists(), "fora.md não pode existir fora da pasta")
                self.assertFalse(out_dir.exists() and any(out_dir.rglob("*")), "nada gravado em --to")
                self.assertEqual(self.state(), before)


class DoctorTest(BackupCliTestCase):
    def backup_rows(self):
        out = self.box.run("doctor")
        self.assertNotIn("Traceback", output(out))
        return [row for row in doctor_lines(out.stdout) if row[1] == "backup" or row[1].startswith("backup ")]

    def test_doctor_reports_each_target(self):
        """SPEC-0051:IT-08"""
        self.shared_block("backup:\n  warn_days: 7\n")
        recent, old, empty, missing = (self.box.root / f"backups-{n}" for n in ("hoje", "velho", "vazio", "sumiu"))
        for folder in (recent, old, empty, missing):
            folder.mkdir()
            self.add_target(folder)
        moment = dt.datetime.now().replace(microsecond=0) - dt.timedelta(minutes=1)
        fresh = self.fake_backup(recent, moment)
        stale = self.fake_backup(old, moment - dt.timedelta(days=10))
        shutil.rmtree(missing)
        rows = {row[1]: row for row in self.backup_rows()}
        self.assertEqual(rows.get(f"backup {recent}", ("",))[0], "OK", rows)
        self.assertIn(fresh.name, rows[f"backup {recent}"][2])
        self.assertEqual(rows.get(f"backup {old}", ("",))[0], "AVISO", rows)
        self.assertRegex(rows[f"backup {old}"][2], r"10 dia")
        self.assertIn(stale.name, rows[f"backup {old}"][2])
        self.assertEqual(rows.get(f"backup {empty}", ("",))[0], "AVISO", rows)
        self.assertIn("nenhum backup", rows[f"backup {empty}"][2])
        self.assertEqual(rows.get(f"backup {missing}", ("",))[0], "AVISO", rows)
        self.assertIn("inacessível", rows[f"backup {missing}"][2])

    def test_doctor_warns_when_no_target_is_configured(self):
        """SPEC-0051:IT-08"""
        rows = self.backup_rows()
        self.assertIn(("AVISO", "backup", "nenhum destino configurado (references/backup.md)"), rows)
