"""IDs das pastas do conector na configuração compartilhada: leitura, doctor e caracterização (SPEC-0110: UT-05,
CH-01; ADR-0013, ADR-0027).

Contrato (seção 6 da SPEC-0110):

    brain-config.yml (compartilhada, opcional)
      connectors:
        google-drive:
          vault_folder_id: <ID>
          inbox_folder_id: <ID>        # opcional

    `connectors` entra em SHARED_KEYS: read_config / load_config devolvem values["connectors"] ({} sem a chave).
    doctor
      AVISO "connectors.<x>" — "provedor desconhecido"      (x fora de PROVIDERS)
      ERRO  "connectors.<p>.<campo>" — "id inválido"         (fora de ^[A-Za-z0-9_-]{8,128}$ ou com cara de segredo)
      sem AVISO de chave desconhecida para `connectors` válido.

CH-01 guarda o que não muda num vault sem `connectors`: as chaves do `config --json` (fora `connectors`), os itens
do `doctor` e o `capture --print`. Os IDs dos testes são fictícios, no formato dos IDs de pasta do Drive.
"""
import json
import re
import unittest

from brain_support import SCRIPT, Sandbox, doctor_lines, fn, output

VAULT_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
INBOX_ID = "2KlMnOpQrStUvWxYz0123456789AbCdE"

# SPEC-0110:CH-01 — o que o código de hoje mostra num vault do init, sem `connectors`.
TODAY_VALUES = {"backup", "backup_targets", "conflict_patterns", "contexts", "files", "inbox_stale_days", "language",
                "layout", "lint", "para", "processors", "provider", "timezone", "vault", "version"}
TODAY_DOCTOR_ITEMS = [
    ("OK", "configuração local"), ("OK", "vault"), ("OK", "files"),
    ("AVISO", "vault"), ("AVISO", "vault (pasta-mãe)"), ("AVISO", "files"), ("AVISO", "files (pasta-mãe)"),
    ("OK", "brain-config.yml"), ("OK", "timezone"),
    ("OK", "layout.inbox"), ("OK", "layout.raw"), ("OK", "layout.mocs"), ("OK", "layout.templates"),
    ("OK", "layout.index"), ("OK", "layout.log"),
    ("OK", "para.projects"), ("OK", "para.areas"), ("OK", "para.resources"), ("OK", "para.archive"),
    ("OK", "contextos"), ("OK", "processadores"), ("OK", "lint"), ("OK", "confidential"),
    ("AVISO", "backup"), ("AVISO", "provider google-drive"),
]


def connectors_block(providers: dict) -> str:
    lines = ["connectors:"]
    for name, ids in providers.items():
        lines.append(f"  {name}:")
        lines += [f"    {key}: {value}" for key, value in ids.items()]
    return "\n".join(lines) + "\n"


class ConnectorIdsTestCase(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.fail(f"{SCRIPT} não existe (SPEC-0110)")
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.vault.mkdir(parents=True)
        out = self.box.init()
        self.assertEqual(out.returncode, 0, output(out))
        self.shared = self.box.vault / "brain-config.yml"

    def write_connectors(self, providers: dict):
        text = self.shared.read_text(encoding="utf-8")
        self.shared.write_text(text.rstrip("\n") + "\n" + connectors_block(providers), encoding="utf-8")

    def doctor(self):
        return self.box.run("doctor")


class ConnectorIdsReadTest(ConnectorIdsTestCase):
    def test_valid_connectors_are_read_and_not_an_unknown_key(self):
        """SPEC-0110:UT-05"""
        # SPEC-0110:UT-05
        ids = {"vault_folder_id": VAULT_ID, "inbox_folder_id": INBOX_ID}
        self.write_connectors({"google-drive": ids})
        config = fn("read_config", "SPEC-0110")(self.box.config_home)
        self.assertEqual(config["values"].get("connectors"), {"google-drive": ids},
                         "read_config: values['connectors'] com os IDs gravados")
        self.assertFalse([p for p in config["problems"] if "connectors" in p[0]], config["problems"])

        out = self.doctor()
        self.assertNotIn("Traceback", output(out))
        rows = doctor_lines(out.stdout)
        unknown = [r for r in rows if r[1] == "brain-config.yml" and "desconhecida" in r[2]]
        self.assertEqual(unknown, [], f"connectors válido não é chave desconhecida: {unknown}")
        self.assertFalse([r for r in rows if r[0] in ("AVISO", "ERRO") and r[1].startswith("connectors")], rows)
        self.assertEqual(out.returncode, 0, output(out))

    def test_doctor_reports_an_invalid_id_written_by_hand(self):
        """SPEC-0110:UT-05"""
        # SPEC-0110:UT-05
        self.write_connectors({"google-drive": {"vault_folder_id": "curto", "inbox_folder_id": INBOX_ID}})
        out = self.doctor()
        self.assertNotIn("Traceback", output(out))
        rows = doctor_lines(out.stdout)
        errors = [r for r in rows if r[0] == "ERRO" and r[1] == "connectors.google-drive.vault_folder_id"]
        self.assertTrue(errors, f"doctor: ERRO connectors.google-drive.vault_folder_id — id inválido\n{out.stdout}")
        self.assertRegex(errors[0][2], r"id inválido")
        self.assertFalse([r for r in rows if r[1] == "connectors.google-drive.inbox_folder_id" and r[0] == "ERRO"],
                         "o inbox_folder_id válido não vira ERRO")
        self.assertEqual(out.returncode, 1, output(out))

    def test_doctor_reports_a_secret_looking_id(self):
        """SPEC-0110:UT-05"""
        # SPEC-0110:UT-05
        token = "ghp" + "_" + "Ab1" * 12  # formato de token, fictício (detector da SPEC-0050)
        self.write_connectors({"google-drive": {"vault_folder_id": VAULT_ID, "inbox_folder_id": token}})
        rows = doctor_lines(self.doctor().stdout)
        self.assertTrue([r for r in rows if r[0] == "ERRO" and r[1] == "connectors.google-drive.inbox_folder_id"
                         and "id inválido" in r[2]], rows)

    def test_doctor_warns_about_an_unknown_provider(self):
        """SPEC-0110:UT-05"""
        # SPEC-0110:UT-05
        self.write_connectors({"google-drive": {"vault_folder_id": VAULT_ID}, "dropbox": {"vault_folder_id": VAULT_ID}})
        out = self.doctor()
        rows = doctor_lines(out.stdout)
        warn = [r for r in rows if r[0] == "AVISO" and r[1] == "connectors.dropbox"]
        self.assertTrue(warn, f"doctor: AVISO connectors.dropbox — provedor desconhecido\n{out.stdout}")
        self.assertRegex(warn[0][2], r"provedor desconhecido")
        self.assertFalse([r for r in rows if r[0] == "ERRO" and r[1].startswith("connectors")], rows)


class WithoutConnectorsCharacterizationTest(ConnectorIdsTestCase):
    def test_config_json_keeps_todays_keys(self):
        """SPEC-0110:CH-01"""
        # SPEC-0110:CH-01
        config = self.box.config_json()
        self.assertEqual(set(config) - {"connectors"}, {"values", "origins"})
        self.assertEqual(set(config["values"]) - {"connectors"}, TODAY_VALUES)
        self.assertEqual(config["values"]["contexts"], {})
        self.assertEqual(config["values"]["layout"]["inbox"], "inbox")

    def test_doctor_keeps_todays_items(self):
        """SPEC-0110:CH-01"""
        # SPEC-0110:CH-01
        out = self.doctor()
        self.assertEqual(out.returncode, 0, output(out))
        rows = doctor_lines(out.stdout)
        self.assertEqual([(status, item) for status, item, _ in rows], TODAY_DOCTOR_ITEMS, out.stdout)
        self.assertNotRegex(out.stdout, r"(?m)^(AVISO|ERRO) connectors")
        self.assertNotIn("desconhecida", out.stdout)

    def test_capture_print_is_unchanged(self):
        """SPEC-0110:CH-01"""
        # SPEC-0110:CH-01
        out = self.box.run("capture", "ideia sobre grafos", "--print", "--json")
        self.assertEqual(out.returncode, 0, output(out))
        data = json.loads(out.stdout)
        self.assertEqual(set(data), {"path", "content"})
        self.assertRegex(data["path"], r"^inbox/\d{4}-\d{2}-\d{2}-\d{6}-ideia-sobre-grafos\.md$")
        self.assertTrue(re.match(r"^---\ntype: capture\ncreated: \S+\n---\n\nideia sobre grafos\n$", data["content"]),
                        data["content"])


if __name__ == "__main__":
    unittest.main()
