"""Fuso do vault pela CLI: capture, capture --print --timezone, doctor, comandos que gravam datas e a
documentação (SPEC-0109: CH-01, UT-02 a UT-07, IT-01).

Cada teste roda o `brain.py` real num Sandbox (HOME, XDG_CONFIG_HOME e BRAIN_CONFIG_HOME temporários). Só o `TZ` do
processo filho muda; o do processo de teste fica como está. Como a hora exata não pode ser fixada pela CLI (o
`brain.py` não tem variável de ambiente de teste), os testes conferem o deslocamento do `created`, a coerência entre
o nome do arquivo e o `created` e que o `created` é o instante da execução (poucos minutos de folga).

Contrato conferido (seção 6):
    brain-config.yml: timezone: America/Sao_Paulo (opcional; sem a chave, o fuso da máquina)
    created da captura: AAAA-MM-DDTHH:MM:SS±HH:MM; nome: AAAA-MM-DD-HHMMSS-<slug> na mesma hora
    capture --print [--timezone NOME]: sem configuração legível vale NOME; com a chave, vale a chave (aviso no stderr)
    doctor: OK "fuso: <nome>" | OK "fuso: o da máquina (±HH:MM)"; ERRO "timezone inválido: ..." | ERRO "fuso <nome>
    não encontrado nesta máquina (instale a base de fusos)"; comandos que gravam datas: exit 2, nada gravado.
"""
import datetime as dt
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from brain_support import SCRIPT, SKILL, doctor_lines, fn, output, snapshot
from test_cli import CliTestCase

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

COLLEGE = ("--context", "college=projects/college:College")
CAPTURE_PATH = re.compile(r"(?:^|/)(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})-ideia-sobre-grafos(?:-\d+)?\.md$")
CREATED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})([+-]\d{2}:\d{2})$")
LOG_ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (\S+)", re.MULTILINE)
INVALID = "timezone inválido: use um nome como America/Sao_Paulo"
SLACK = dt.timedelta(minutes=5)


def zone(name):
    if ZoneInfo is None:
        raise unittest.SkipTest("zoneinfo indisponível")
    try:
        return ZoneInfo(name)
    except Exception as exc:  # sem a base de fusos na máquina de teste
        raise unittest.SkipTest(f"fuso {name} indisponível nesta máquina: {exc}") from exc


def dates_in(name, *moments):
    tz = zone(name)
    return {m.astimezone(tz).date().isoformat() for m in moments}


class TimezoneCliTestCase(CliTestCase):
    def run_tz(self, tz, *args, cwd=None):
        """brain.py com o TZ só no processo filho."""
        env = self.box.env()
        env["BRAIN_CONFIG_HOME"] = str(self.box.config_home)
        env["TZ"] = tz
        return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False,
                              cwd=cwd or self.box.root, capture_output=True, text=True, env=env)

    def make_vault(self, timezone=None):
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(*COLLEGE), 0)
        if timezone is not None:
            self.set_timezone(timezone)

    def set_timezone(self, timezone):
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = self.box.vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        data["timezone"] = timezone
        shared.write_text(dump(data), encoding="utf-8")
        self.assertEqual(parse(shared.read_text(encoding="utf-8")).get("timezone"), timezone)

    def note(self, rel, text=None):
        return fn("parse_note", "SPEC-0018")(rel, text if text is not None else
                                            (self.box.vault / rel).read_text(encoding="utf-8"), None)

    def check_capture(self, path, content, offset, before, after):
        """created com o deslocamento `offset`, o nome na mesma data e hora e o instante da execução."""
        note = self.note(path, content)
        self.assertEqual(note.frontmatter.get("type"), "capture")
        created = str(note.frontmatter.get("created") or "")
        m = CREATED.match(created)
        self.assertTrue(m, f"created sem deslocamento (AAAA-MM-DDTHH:MM:SS±HH:MM): {created!r}")
        self.assertEqual(m.group(7), offset, created)
        n = CAPTURE_PATH.search(path)
        self.assertTrue(n, f"nome da captura fora do contrato: {path}")
        self.assertEqual(n.groups(), m.groups()[:6], f"nome e created na mesma hora: {path} / {created}")
        moment = dt.datetime.fromisoformat(created)
        self.assertTrue(before - SLACK <= moment <= after + SLACK, f"created não é o instante da execução: {created}")
        return note

    def capture_print(self, tz, *extra):
        before = dt.datetime.now(dt.timezone.utc)
        out = self.run_tz(tz, "capture", "Ideia sobre grafos", "--print", "--json", *extra)
        after = dt.datetime.now(dt.timezone.utc)
        return out, before, after

    def print_data(self, out):
        self.assertExit(out, 0)
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")
        return data


class CharacterizationTest(TimezoneCliTestCase):
    def test_capture_without_the_key_keeps_name_body_and_type(self):
        """SPEC-0109:CH-01"""
        # SPEC-0109:CH-01
        self.make_vault()
        out = self.run_tz("America/Sao_Paulo", "capture", "Ideia sobre grafos", "--context", "college")
        self.assertExit(out, 0)
        printed = [line for line in out.stdout.splitlines() if line.strip()]
        path = Path(printed[-1].strip())
        rel = path.relative_to(self.box.vault).as_posix() if path.is_absolute() else path.as_posix()
        self.assertRegex(rel, r"^inbox/\d{4}-\d{2}-\d{2}-\d{6}-ideia-sobre-grafos\.md$")
        text = (self.box.vault / rel).read_text(encoding="utf-8")
        note = self.note(rel, text)
        self.assertEqual(note.frontmatter.get("type"), "capture")
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertEqual(set(note.frontmatter), {"type", "created", "context"})
        self.assertTrue(text.endswith("---\n\nIdeia sobre grafos\n"), text)
        created = str(note.frontmatter.get("created") or "")
        stamp = CAPTURE_PATH.search(rel).groups()
        self.assertEqual(re.findall(r"\d+", created)[:6], list(stamp), f"nome e created na mesma hora: {created}")


class MachineZoneCliTest(TimezoneCliTestCase):
    def test_without_configuration_the_machine_zone_gives_the_offset(self):
        """SPEC-0109:UT-02"""
        # SPEC-0109:UT-02
        zone("America/Sao_Paulo")
        for tz, offset in (("America/Sao_Paulo", "-03:00"), ("UTC", "+00:00")):
            with self.subTest(TZ=tz):
                out, before, after = self.capture_print(tz)
                data = self.print_data(out)
                self.check_capture(data["path"], data["content"], offset, before, after)

    def test_without_the_key_in_the_vault_the_machine_zone_gives_the_offset(self):
        """SPEC-0109:UT-02"""
        # SPEC-0109:UT-02
        zone("America/Sao_Paulo")
        self.make_vault()
        before = dt.datetime.now(dt.timezone.utc)
        out = self.run_tz("America/Sao_Paulo", "capture", "Ideia sobre grafos", "--json")
        after = dt.datetime.now(dt.timezone.utc)
        self.assertExit(out, 0)
        rel = json.loads(out.stdout)["path"]
        rel = Path(rel).relative_to(self.box.vault).as_posix() if Path(rel).is_absolute() else rel
        self.check_capture(rel, (self.box.vault / rel).read_text(encoding="utf-8"), "-03:00", before, after)


class InvalidZoneCliTest(TimezoneCliTestCase):
    CASES = (("../etc/passwd", INVALID), ("Not/A/Zone/Too/Deep", INVALID),
             ("Mars/Olympus", "fuso Mars/Olympus não encontrado nesta máquina (instale a base de fusos)"))

    def test_doctor_errors_writers_exit_2_and_readers_go_on(self):
        """SPEC-0109:UT-03"""
        # SPEC-0109:UT-03
        self.make_vault()
        (self.box.vault / "resources").mkdir(exist_ok=True)
        (self.box.vault / "resources" / "grafos.md").write_text("# Grafos\n\nNota sobre grafos.\n", encoding="utf-8")
        for name, message in self.CASES:
            with self.subTest(timezone=name):
                self.set_timezone(name)
                out = self.run_tz("UTC", "doctor")
                self.assertNotIn("Traceback", output(out))
                errors = [f"{item} — {detail}" for status, item, detail in doctor_lines(out.stdout)
                          if status == "ERRO"]
                self.assertTrue(any(message in line for line in errors), f"ERRO {message!r} ausente:\n{output(out)}")

                before = snapshot(self.box.vault)
                for args in (("capture", "Ideia sobre grafos"),
                             ("new-note", "--type", "note", "--title", "Aula fuso", "--context", "college")):
                    out = self.run_tz("UTC", *args)
                    self.assertExit(out, 2)
                    self.assertIn(message, output(out))
                    self.assertEqual(snapshot(self.box.vault), before, f"{args[0]} não grava nada")

                self.assertExit(self.run_tz("UTC", "search", "grafos"), 0)
                self.assertExit(self.run_tz("UTC", "config"), 0)


class ConnectorTimezoneCliTest(TimezoneCliTestCase):
    def test_print_without_configuration_uses_the_timezone_option(self):
        """SPEC-0109:UT-04"""
        # SPEC-0109:UT-04
        zone("America/Sao_Paulo")
        out, before, after = self.capture_print("Asia/Tokyo", "--timezone", "America/Sao_Paulo")
        data = self.print_data(out)
        self.check_capture(data["path"], data["content"], "-03:00", before, after)

    def test_print_with_the_key_ignores_a_different_option_and_warns(self):
        """SPEC-0109:UT-04"""
        # SPEC-0109:UT-04
        zone("Europe/Lisbon")
        self.make_vault(timezone="Europe/Lisbon")
        out, before, after = self.capture_print("Asia/Tokyo", "--timezone", "America/Sao_Paulo")
        data = self.print_data(out)
        offset = dt.datetime.now(zone("Europe/Lisbon")).strftime("%z")
        self.check_capture(data["path"], data["content"], f"{offset[:3]}:{offset[3:]}", before, after)
        self.assertTrue(out.stderr.strip(), "o stderr avisa que o --timezone foi ignorado")
        self.assertTrue("Europe/Lisbon" in out.stderr or "America/Sao_Paulo" in out.stderr, out.stderr)


class NotesAndLogCliTest(TimezoneCliTestCase):
    def test_note_date_and_log_time_follow_the_vault_zone(self):
        """SPEC-0109:UT-05"""
        # SPEC-0109:UT-05
        tz = zone("America/Sao_Paulo")
        self.make_vault(timezone="America/Sao_Paulo")
        log_before = (self.box.vault / "log.md").read_text(encoding="utf-8")
        before = dt.datetime.now(dt.timezone.utc)
        out = self.run_tz("Pacific/Kiritimati", "new-note", "--type", "note", "--title", "Aula fuso",
                          "--context", "college", "--json")
        after = dt.datetime.now(dt.timezone.utc)
        self.assertExit(out, 0)
        rel = json.loads(out.stdout)["path"]
        rel = Path(rel).relative_to(self.box.vault).as_posix() if Path(rel).is_absolute() else rel
        self.assertIn(str(self.note(rel).frontmatter.get("created")), dates_in("America/Sao_Paulo", before, after))
        log = (self.box.vault / "log.md").read_text(encoding="utf-8")[len(log_before):]
        entries = [m.group(1) for m in LOG_ENTRY.finditer(log)]
        self.assertTrue(entries, log)
        stamp = dt.datetime.strptime(entries[-1], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        self.assertTrue(before - SLACK <= stamp <= after + SLACK, f"hora do log fora do fuso do vault: {entries[-1]}")


class BackupTimezoneCliTest(TimezoneCliTestCase):
    def backup(self, tz):
        dest = self.box.root / "backups"
        dest.mkdir(exist_ok=True)
        return self.run_tz(tz, "backup", "--dest", dest, "--json"), dest

    def test_backup_with_an_invalid_timezone_exits_2_without_log_nor_zip(self):
        """SPEC-0109:UT-03"""
        # SPEC-0109:UT-03
        self.make_vault(timezone="../etc/passwd")
        log_before = (self.box.vault / "log.md").read_text(encoding="utf-8")
        out, dest = self.backup("UTC")
        self.assertExit(out, 2)
        self.assertIn(INVALID, output(out))
        self.assertEqual((self.box.vault / "log.md").read_text(encoding="utf-8"), log_before, "nada no log.md")
        self.assertEqual(sorted(p.name for p in dest.rglob("*")), [], "nenhum zip (nem .partial) criado")

    def test_backup_log_line_uses_the_vault_zone_like_a_capture(self):
        """SPEC-0109:UT-05"""
        # SPEC-0109:UT-05
        tz = zone("Asia/Tokyo")
        self.make_vault(timezone="Asia/Tokyo")
        log_before = (self.box.vault / "log.md").read_text(encoding="utf-8")
        before = dt.datetime.now(dt.timezone.utc)
        self.assertExit(self.run_tz("UTC", "capture", "Ideia sobre grafos"), 0)
        out, _ = self.backup("UTC")
        after = dt.datetime.now(dt.timezone.utc)
        self.assertExit(out, 0)
        log = (self.box.vault / "log.md").read_text(encoding="utf-8")[len(log_before):]
        stamps = {command: dt.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                  for when, command in LOG_ENTRY.findall(log)}
        self.assertEqual(set(stamps), {"capture", "backup"}, log)
        for command, stamp in stamps.items():
            with self.subTest(command=command):
                self.assertTrue(before - SLACK <= stamp <= after + SLACK,
                                f"hora do log de {command} fora do fuso do vault: {stamp:%Y-%m-%d %H:%M}\n{log}")
        gap = stamps["backup"] - stamps["capture"]
        self.assertTrue(dt.timedelta(0) <= gap <= SLACK, f"backup e captura no mesmo fuso: {log}")


class DoctorZoneCliTest(TimezoneCliTestCase):
    def test_timezone_key_is_known_and_doctor_shows_the_zone_in_use(self):
        """SPEC-0109:UT-06"""
        # SPEC-0109:UT-06
        zone("America/Sao_Paulo")
        self.make_vault()
        out = self.run_tz("America/Sao_Paulo", "doctor")
        self.assertRegex(out.stdout, r"(?m)^OK .*fuso: o da máquina \(-03:00\)")
        self.set_timezone("America/Sao_Paulo")
        out = self.run_tz("UTC", "doctor")
        rows = doctor_lines(out.stdout)
        unknown = [row for row in rows if "chaves desconhecidas" in row[2]]
        self.assertEqual(unknown, [], "timezone é chave conhecida do brain-config.yml")
        self.assertRegex(out.stdout, r"(?m)^OK .*fuso: America/Sao_Paulo")


class DocumentationTest(unittest.TestCase):
    def read(self, rel):
        return (SKILL / rel).read_text(encoding="utf-8")

    def test_references_and_skill_describe_the_key_and_the_format(self):
        """SPEC-0109:UT-07"""
        # SPEC-0109:UT-07
        config = self.read("references/config.md")
        self.assertIn("timezone", config)
        self.assertIn("IANA", config)
        self.assertIn("America/Sao_Paulo", config)
        self.assertRegex(config, r"(?is)timezone.{0,400}(fuso da máquina|fuso local da máquina)")
        offset = r"created: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}"
        for rel in ("references/connectors.md", "references/inbox.md"):
            with self.subTest(doc=rel):
                text = self.read(rel)
                self.assertRegex(text, offset, f"{rel} mostra o created com deslocamento")
                self.assertIn("--timezone", text)
        skill = self.read("SKILL.md")
        capture = re.search(r"(?s)\*\*Capturar.*?(?=\n- \*\*|\n#)", skill)
        self.assertTrue(capture, "fluxo de captura no SKILL.md")
        self.assertIn("timezone", capture.group(0))


class InboxFlowTimezoneTest(TimezoneCliTestCase):
    def test_capture_list_and_ingest_move_follow_the_vault_zone_on_a_utc_machine(self):
        """SPEC-0109:IT-01"""
        # SPEC-0109:IT-01
        zone("America/Sao_Paulo")
        self.make_vault(timezone="America/Sao_Paulo")
        before = dt.datetime.now(dt.timezone.utc)
        out = self.run_tz("UTC", "capture", "Ideia sobre grafos", "--context", "college", "--json")
        self.assertExit(out, 0)
        rel = json.loads(out.stdout)["path"]
        rel = Path(rel).relative_to(self.box.vault).as_posix() if Path(rel).is_absolute() else rel
        self.check_capture(rel, (self.box.vault / rel).read_text(encoding="utf-8"), "-03:00", before,
                           dt.datetime.now(dt.timezone.utc))

        out = self.run_tz("UTC", "inbox", "list", "--json", cwd=self.box.vault)
        self.assertExit(out, 0)
        items = {item["path"]: item for item in json.loads(out.stdout)["items"]}
        item = next((v for k, v in items.items() if k.endswith(Path(rel).name)), None)
        self.assertIsNotNone(item, items)
        self.assertGreaterEqual(item["age_days"], 0)
        self.assertLess(item["age_days"], 0.01, "idade da captura recém-criada")
        self.assertFalse(item["stale"])

        pdf = self.box.vault / "inbox" / "aula.pdf"
        pdf.write_bytes(b"%PDF-1.4 aula de grafos")
        out = self.run_tz("UTC", "ingest", "inbox/aula.pdf", "--move", "--context", "college", "--json",
                          cwd=self.box.vault)
        after = dt.datetime.now(dt.timezone.utc)
        self.assertExit(out, 0)
        raw = json.loads(out.stdout)["raw"]
        raw = Path(raw).relative_to(self.box.vault).as_posix() if Path(raw).is_absolute() else raw
        created = str(self.note(raw).frontmatter.get("created"))
        self.assertIn(created, dates_in("America/Sao_Paulo", before, after), "data da nota no fuso do vault")


if __name__ == "__main__":
    unittest.main()
