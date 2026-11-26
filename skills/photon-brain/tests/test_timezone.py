"""Fuso do vault nas funções puras de data: vault_clock, capture_note, capture_name, now e today (SPEC-0109).

Interface que os testes conferem (seções 4 e 6 da spec):
    vault_clock(shared, override=None, clock=None) -> relógio (callable sem argumentos -> datetime com tzinfo)
        shared: a configuração compartilhada (dict); a chave `timezone` (nome IANA) vale sobre `override`
        (o --timezone do capture --print); sem as duas, o fuso da máquina (astimezone()). `clock`: o instante de
        base (callable -> datetime com fuso; None = agora), só para os testes fixarem o instante.
        Nome fora de ^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$ -> BrainError(code 2)
        "timezone inválido: use um nome como America/Sao_Paulo"; nome que o zoneinfo não acha -> BrainError(code 2)
        "fuso <nome> não encontrado nesta máquina (instale a base de fusos)".
    capture_note(text, context=None, clock=relógio) -> created "AAAA-MM-DDTHH:MM:SS±HH:MM"
    capture_name(text, existing=(), clock=relógio) -> "AAAA-MM-DD-HHMMSS-<slug>.md" na hora do mesmo fuso
    now(clock=relógio) -> "AAAA-MM-DD HH:MM"; today(clock=relógio) -> "AAAA-MM-DD"

Os instantes fixos entram só pelo parâmetro `clock=`; o TZ do processo de teste só muda com time.tzset e é
restaurado no addCleanup (UT-02, UT-05).
"""
import datetime as dt
import os
import time
import unittest

from brain_support import brain, fn

SPEC = "SPEC-0109"
UTC = dt.timezone.utc
SAO_PAULO = dt.timedelta(hours=-3)
INVALID = "timezone inválido: use um nome como America/Sao_Paulo"


def fixed(*parts):
    instant = dt.datetime(*parts, tzinfo=UTC)
    return lambda: instant


class TzMixin:
    def set_process_tz(self, name):
        """TZ do próprio processo de teste, restaurado ao fim do teste."""
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset indisponível nesta plataforma")
        old = os.environ.get("TZ")

        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = name
        time.tzset()


class VaultClockCaptureTest(unittest.TestCase):
    def test_configured_zone_gives_created_with_offset_and_name_in_the_same_hour(self):
        """SPEC-0109:UT-01"""
        # SPEC-0109:UT-01
        clock = fn("vault_clock", SPEC)({"timezone": "America/Sao_Paulo"}, clock=fixed(2026, 11, 26, 12, 15, 2))
        moment = clock()
        self.assertIsNotNone(moment.tzinfo, "o relógio do vault tem fuso")
        self.assertEqual(moment.utcoffset(), SAO_PAULO)
        note = fn("capture_note", SPEC)("Ideia sobre grafos", clock=clock)
        self.assertEqual(note, "---\ntype: capture\ncreated: 2026-11-26T09:15:02-03:00\n---\n\nIdeia sobre grafos\n")
        name = fn("capture_name", SPEC)("Ideia sobre grafos", clock=clock)
        self.assertTrue(name.startswith("2026-11-26-091502-"), name)


class MachineZoneTest(TzMixin, unittest.TestCase):
    def test_without_the_key_the_machine_zone_gives_the_offset(self):
        """SPEC-0109:UT-02"""
        # SPEC-0109:UT-02
        vault_clock, capture_note = fn("vault_clock", SPEC), fn("capture_note", SPEC)
        for zone, offset, suffix in (("America/Sao_Paulo", SAO_PAULO, "-03:00"), ("UTC", dt.timedelta(0), "+00:00")):
            with self.subTest(TZ=zone):
                self.set_process_tz(zone)
                clock = vault_clock({})
                self.assertEqual(clock().utcoffset(), offset)
                created = [line for line in capture_note("x", clock=clock).splitlines()
                           if line.startswith("created:")]
                self.assertEqual(len(created), 1, created)
                self.assertTrue(created[0].strip().strip("'\"").endswith(suffix), created[0])
                pinned = vault_clock({}, clock=fixed(2026, 11, 26, 12, 15, 2))()
                self.assertEqual(pinned.utcoffset(), offset, "o instante fixo sai no fuso da máquina")


class InvalidZoneTest(unittest.TestCase):
    def test_invalid_or_unknown_names_raise_code_2_with_the_doctor_message(self):
        """SPEC-0109:UT-03"""
        # SPEC-0109:UT-03
        vault_clock, error = fn("vault_clock", SPEC), brain().BrainError
        cases = (("../etc/passwd", INVALID), ("Not/A/Zone/Too/Deep", INVALID), ("/etc/localtime", INVALID),
                 ("Mars/Olympus", "fuso Mars/Olympus não encontrado nesta máquina (instale a base de fusos)"))
        for name, message in cases:
            with self.subTest(timezone=name):
                with self.assertRaises(error) as caught:
                    vault_clock({"timezone": name})()
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(message, str(caught.exception))


class OverrideTest(unittest.TestCase):
    def test_override_only_counts_without_the_key(self):
        """SPEC-0109:UT-04"""
        # SPEC-0109:UT-04
        vault_clock = fn("vault_clock", SPEC)
        base = fixed(2026, 11, 26, 12, 15, 2)
        self.assertEqual(vault_clock({}, override="America/Sao_Paulo", clock=base)().utcoffset(), SAO_PAULO)
        self.assertEqual(vault_clock(None, override="America/Sao_Paulo", clock=base)().utcoffset(), SAO_PAULO,
                         "sem configuração legível vale o --timezone")
        lisbon = vault_clock({"timezone": "Europe/Lisbon"}, override="America/Sao_Paulo", clock=base)()
        self.assertEqual(lisbon.utcoffset(), dt.timedelta(0), "lida a configuração, vale a chave")
        self.assertEqual(lisbon.strftime("%H:%M:%S"), "12:15:02")


class NotesAndLogDatesTest(TzMixin, unittest.TestCase):
    def test_note_date_and_log_time_follow_the_vault_zone_near_utc_midnight(self):
        """SPEC-0109:UT-05"""
        # SPEC-0109:UT-05
        self.set_process_tz("UTC")
        clock = fn("vault_clock", SPEC)({"timezone": "America/Sao_Paulo"}, clock=fixed(2026, 11, 27, 1, 30, 0))
        self.assertEqual(fn("today", SPEC)(clock=clock), "2026-11-26")
        self.assertEqual(fn("now", SPEC)(clock=clock), "2026-11-26 22:30")


class SharedKeyTest(unittest.TestCase):
    def test_timezone_is_a_shared_key(self):
        """SPEC-0109:UT-06"""
        # SPEC-0109:UT-06
        self.assertIn("timezone", brain().SHARED_KEYS)


if __name__ == "__main__":
    unittest.main()
