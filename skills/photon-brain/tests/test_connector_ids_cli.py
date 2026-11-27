"""`brain.py connector set|show` e `connectors` no `config --json` (SPEC-0110: UT-01 a UT-04, IT-01; ADR-0013,
ADR-0027).

Contrato (seção 6 da SPEC-0110):

    brain.py connector set PROVEDOR --vault-folder-id ID [--inbox-folder-id ID]
      PROVEDOR em PROVIDERS (google-drive, onedrive, icloud, local)
      sucesso (exit 0): "ids do conector google-drive gravados"; o resto do brain-config.yml não muda
        log.md: "- <agora> connector set google-drive"  (só o provedor, nunca os IDs)
      erros (exit 2, nada gravado): provedor desconhecido | ID fora de ^[A-Za-z0-9_-]{8,128}$ ou com cara de segredo
      erro (exit 3): sem configuração

    brain.py connector show [--json]
      "google-drive: vault <ID>, inbox <ID>" por provedor | {"google-drive": {"vault_folder_id", "inbox_folder_id"}}
      sem a chave: "nenhum id de conector gravado" (exit 0)
      (v2) ID escrito à mão fora da regra ou com cara de segredo aparece como "(inválido)", nunca o valor

    (v2) com vários provedores em connectors (e comentários entre eles), connector set muda só o provedor pedido;
    os outros ficam byte a byte iguais. timezone inválido no brain-config.yml: exit 2, nada gravado.

    brain.py config --json
      values["connectors"] com os IDs gravados ({} sem a chave)

Os IDs são fictícios, no formato dos IDs de pasta do Google Drive.
"""
import json
import re
import unittest

from brain_support import SCRIPT, Sandbox, doctor_lines, fn, output, snapshot

VAULT_ID = "1AbCdEfGhIj"
INBOX_ID = "2KlMnOpQrSt"
OTHER_VAULT_ID = "1ZyXwVuTsRqPoNmLkJiHgFeDcBa98765"
NEW_INBOX_ID = "3QwErTyUiOpAsDfGhJkL"
ONEDRIVE_BLOCK = ("  # pasta do OneDrive (conferida à mão)\n"
                  "  onedrive:\n"
                  "    vault_folder_id: 4ZxCvBnMaSdFgHjK\n"
                  "    inbox_folder_id: 5PoIuYtReWqLkJhG\n")
ICLOUD_BLOCK = ("  # iCloud por último\n"
                "  icloud:\n"
                "    vault_folder_id: 6MnBvCxZlKjHgFdS\n")
TOKEN = "ghp" + "_" + "Ab1" * 12  # formato de token, fictício (detector da SPEC-0050)
SET_LOG = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} connector set google-drive\s*$")


class ConnectorCliTestCase(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.fail(f"{SCRIPT} não existe (SPEC-0110)")
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.new_vault()
        self.shared = self.box.vault / "brain-config.yml"
        self.log = self.box.vault / "log.md"

    def assertExit(self, result, code):
        self.assertNotIn("Traceback", output(result))
        self.assertEqual(result.returncode, code, output(result))

    def set_ids(self, *args):
        return self.box.run("connector", "set", *args)

    def text(self):
        return self.shared.read_text(encoding="utf-8")

    def append(self, block: str):
        self.shared.write_text(self.text().rstrip("\n") + "\n" + block, encoding="utf-8")


class ConnectorSetTest(ConnectorCliTestCase):
    def test_set_writes_the_ids_and_keeps_the_rest_of_the_file(self):
        """SPEC-0110:UT-01"""
        # SPEC-0110:UT-01
        parse_yaml = fn("parse_yaml", "SPEC-0110")
        before = self.text()
        out = self.set_ids("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", INBOX_ID)
        self.assertExit(out, 0)
        self.assertIn("ids do conector google-drive gravados", output(out))
        after = self.text()
        data = parse_yaml(after)
        self.assertEqual(data.get("connectors"),
                         {"google-drive": {"vault_folder_id": VAULT_ID, "inbox_folder_id": INBOX_ID}})
        self.assertEqual({k: v for k, v in data.items() if k != "connectors"}, parse_yaml(before),
                         "as outras chaves ficam iguais")
        lines_after = iter(after.splitlines())
        missing = [line for line in before.splitlines() if not any(line == other for other in lines_after)]
        self.assertEqual(missing, [], "cada linha de antes (comentários inclusive) continua, na mesma ordem")

        out = self.set_ids("google-drive", "--vault-folder-id", OTHER_VAULT_ID, "--inbox-folder-id", INBOX_ID)
        self.assertExit(out, 0)
        self.assertEqual(self.text(), after.replace(VAULT_ID, OTHER_VAULT_ID),
                         "rodar de novo com outro ID só troca o valor")

    def test_set_without_inbox_id_records_only_the_vault_folder(self):
        """SPEC-0110:UT-01"""
        # SPEC-0110:UT-01
        out = self.set_ids("google-drive", "--vault-folder-id", VAULT_ID)
        self.assertExit(out, 0)
        stored = fn("parse_yaml", "SPEC-0110")(self.text()).get("connectors", {}).get("google-drive", {})
        self.assertEqual(stored.get("vault_folder_id"), VAULT_ID)
        self.assertIn(stored.get("inbox_folder_id"), (None, ""), stored)

    def test_invalid_provider_or_id_exits_2_and_changes_nothing(self):
        """SPEC-0110:UT-02"""
        # SPEC-0110:UT-02
        token = TOKEN
        cases = {
            "provedor fora de PROVIDERS": ("dropbox", "--vault-folder-id", VAULT_ID),
            "ID com menos de 8": ("google-drive", "--vault-folder-id", "1AbCdEf"),
            "ID com /": ("google-drive", "--vault-folder-id", "1AbCd/EfGhIj"),
            "ID com espaço": ("google-drive", "--vault-folder-id", "1AbCd EfGhIj"),
            "ID com quebra de linha": ("google-drive", "--vault-folder-id", "1AbCdEf\nGhIjK"),
            "ID com cara de segredo": ("google-drive", "--vault-folder-id", token),
            "inbox inválida": ("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", "2Kl/MnOpQrSt"),
            "inbox com cara de segredo": ("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", token),
        }
        self.assertExit(self.box.run("connector", "show"), 0)  # o comando existe: o exit 2 abaixo é da validação
        before = snapshot(self.box.root)
        for name, args in cases.items():
            with self.subTest(case=name):
                out = self.set_ids(*args)
                self.assertExit(out, 2)
                self.assertEqual(snapshot(self.box.root), before, "nada muda: nem o vault nem a configuração local")

    def test_set_writes_only_the_vault_brain_config_and_the_log(self):
        """SPEC-0110:UT-02"""
        # SPEC-0110:UT-02
        before = snapshot(self.box.root)
        self.assertExit(self.set_ids("google-drive", "--vault-folder-id", VAULT_ID), 0)
        after = snapshot(self.box.root)
        changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        self.assertEqual(changed, ["Drive/Vault/brain-config.yml", "Drive/Vault/log.md"])

    def test_set_without_configuration_exits_3(self):
        """SPEC-0110:UT-02"""
        # SPEC-0110:UT-02
        out = self.box.run("connector", "set", "google-drive", "--vault-folder-id", VAULT_ID,
                           config_home=self.box.root / "sem-config")
        self.assertExit(out, 3)

    def test_set_changes_only_the_requested_provider_among_many(self):
        """SPEC-0110:UT-01 (v2)"""
        # SPEC-0110:UT-01
        parse_yaml = fn("parse_yaml", "SPEC-0110")
        self.append("connectors:\n"
                    "  # pasta do Drive\n"
                    "  google-drive:\n"
                    f"    vault_folder_id: {VAULT_ID}\n" + ONEDRIVE_BLOCK)
        before = self.text()
        out = self.set_ids("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", NEW_INBOX_ID)
        self.assertExit(out, 0)
        after = self.text()
        data = parse_yaml(after)["connectors"]
        self.assertEqual(data["google-drive"], {"vault_folder_id": VAULT_ID, "inbox_folder_id": NEW_INBOX_ID})
        self.assertEqual(data["onedrive"], {"vault_folder_id": "4ZxCvBnMaSdFgHjK", "inbox_folder_id": "5PoIuYtReWqLkJhG"})
        self.assertTrue(after.endswith(ONEDRIVE_BLOCK), "o bloco do onedrive (com o comentário) fica byte a byte igual")
        self.assertEqual(after.replace(f"    inbox_folder_id: {NEW_INBOX_ID}\n", "", 1), before,
                         "só a linha nova do google-drive entra no arquivo")

    def test_set_changes_the_middle_provider_and_keeps_its_neighbours(self):
        """SPEC-0110:UT-01 (v2)"""
        # SPEC-0110:UT-01
        parse_yaml = fn("parse_yaml", "SPEC-0110")
        self.append("connectors:\n"
                    "  google-drive:\n"
                    f"    vault_folder_id: {VAULT_ID}\n" + ONEDRIVE_BLOCK + ICLOUD_BLOCK)
        before = self.text()
        out = self.set_ids("onedrive", "--vault-folder-id", OTHER_VAULT_ID, "--inbox-folder-id", "5PoIuYtReWqLkJhG")
        self.assertExit(out, 0)
        after = self.text()
        self.assertEqual(after, before.replace("4ZxCvBnMaSdFgHjK", OTHER_VAULT_ID),
                         "trocar o ID do provedor do meio só troca o valor; os vizinhos ficam byte a byte iguais")
        out = self.set_ids("onedrive", "--vault-folder-id", OTHER_VAULT_ID)
        self.assertExit(out, 0)
        data = parse_yaml(self.text())["connectors"]
        self.assertEqual(data["google-drive"], {"vault_folder_id": VAULT_ID})
        self.assertEqual(data["icloud"], {"vault_folder_id": "6MnBvCxZlKjHgFdS"})
        self.assertTrue(self.text().endswith(ICLOUD_BLOCK), "o icloud (com o comentário) fica byte a byte igual")

    def test_set_with_an_invalid_timezone_exits_2_and_writes_nothing(self):
        """SPEC-0110:UT-02 (v2)"""
        # SPEC-0110:UT-02
        self.append("timezone: ../etc/passwd\n")
        before = snapshot(self.box.root)
        out = self.set_ids("google-drive", "--vault-folder-id", VAULT_ID)
        self.assertExit(out, 2)
        self.assertIn("timezone inválido", output(out))
        self.assertEqual(snapshot(self.box.root), before, "nada gravado: nem o brain-config.yml nem o log.md")

    def test_log_line_names_the_provider_and_never_the_ids(self):
        """SPEC-0110:UT-03"""
        # SPEC-0110:UT-03
        log_before = self.log.read_text(encoding="utf-8")
        out = self.set_ids("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", INBOX_ID)
        self.assertExit(out, 0)
        log_after = self.log.read_text(encoding="utf-8")
        self.assertTrue(log_after.startswith(log_before), "log.md só recebe linhas no fim")
        new = log_after[len(log_before):]
        self.assertEqual(len(new.splitlines()), 1, new)
        self.assertRegex(new.strip(), SET_LOG)
        for value in (VAULT_ID, INBOX_ID):
            self.assertNotIn(value, log_after, "o log nunca contém os IDs")


class ConnectorShowTest(ConnectorCliTestCase):
    def test_show_without_the_key(self):
        """SPEC-0110:UT-04"""
        # SPEC-0110:UT-04
        out = self.box.run("connector", "show")
        self.assertExit(out, 0)
        self.assertIn("nenhum id de conector gravado", output(out))
        out = self.box.run("connector", "show", "--json")
        self.assertExit(out, 0)
        self.assertEqual(json.loads(out.stdout), {})
        self.assertEqual(self.box.config_json()["values"].get("connectors"), {},
                         "config --json: values['connectors'] = {} sem a chave")

    def test_show_lists_the_ids_by_provider(self):
        """SPEC-0110:UT-04"""
        # SPEC-0110:UT-04
        self.assertExit(self.set_ids("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", INBOX_ID), 0)
        self.assertExit(self.set_ids("onedrive", "--vault-folder-id", OTHER_VAULT_ID), 0)
        out = self.box.run("connector", "show")
        self.assertExit(out, 0)
        self.assertIn(f"google-drive: vault {VAULT_ID}, inbox {INBOX_ID}", out.stdout)
        self.assertRegex(out.stdout, rf"(?m)^onedrive: vault {OTHER_VAULT_ID}")
        out = self.box.run("connector", "show", "--json")
        self.assertExit(out, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["google-drive"], {"vault_folder_id": VAULT_ID, "inbox_folder_id": INBOX_ID})
        self.assertEqual(data["onedrive"]["vault_folder_id"], OTHER_VAULT_ID)
        connectors = self.box.config_json()["values"].get("connectors")
        self.assertEqual(connectors["google-drive"], {"vault_folder_id": VAULT_ID, "inbox_folder_id": INBOX_ID})


    def test_show_masks_an_invalid_id_written_by_hand(self):
        """SPEC-0110:UT-04 (v2)"""
        # SPEC-0110:UT-04
        self.append("connectors:\n"
                    "  google-drive:\n"
                    "    vault_folder_id: curto\n"
                    f"    inbox_folder_id: {TOKEN}\n"
                    "  onedrive:\n"
                    f"    vault_folder_id: {OTHER_VAULT_ID}\n")
        out = self.box.run("connector", "show")
        self.assertExit(out, 0)
        self.assertIn("google-drive: vault (inválido), inbox (inválido)", out.stdout)
        self.assertRegex(out.stdout, rf"(?m)^onedrive: vault {OTHER_VAULT_ID}")
        out_json = self.box.run("connector", "show", "--json")
        self.assertExit(out_json, 0)
        self.assertEqual(json.loads(out_json.stdout)["google-drive"],
                         {"vault_folder_id": "(inválido)", "inbox_folder_id": "(inválido)"})
        config = self.box.run("config", "--json")
        self.assertExit(config, 0)
        self.assertEqual(json.loads(config.stdout)["values"]["connectors"]["google-drive"],
                         {"vault_folder_id": "(inválido)", "inbox_folder_id": "(inválido)"})
        for result in (out, out_json, config):
            for value in ("curto", TOKEN):
                self.assertNotIn(value, output(result), "o valor inválido nunca aparece")

class ConnectorWithContextIntegrationTest(ConnectorCliTestCase):
    def test_connector_set_context_add_and_show_live_together(self):
        """SPEC-0110:IT-01"""
        # SPEC-0110:IT-01
        log_before = self.log.read_text(encoding="utf-8")
        self.assertExit(self.set_ids("google-drive", "--vault-folder-id", VAULT_ID, "--inbox-folder-id", INBOX_ID), 0)
        self.assertExit(self.box.run("context", "add", "work", "--folder", "areas/work", "--title", "Work"), 0)
        out = self.box.run("connector", "show", "--json")
        self.assertExit(out, 0)
        self.assertEqual(json.loads(out.stdout)["google-drive"],
                         {"vault_folder_id": VAULT_ID, "inbox_folder_id": INBOX_ID})

        data = fn("parse_yaml", "SPEC-0110")(self.text())
        self.assertEqual(data["connectors"]["google-drive"]["vault_folder_id"], VAULT_ID)
        self.assertEqual(set(data["contexts"]), {"college", "work"})

        out = self.box.run("doctor")
        self.assertNotIn("Traceback", output(out))
        errors = [r for r in doctor_lines(out.stdout) if r[0] == "ERRO"]
        self.assertEqual(errors, [], out.stdout)
        self.assertEqual(out.returncode, 0, output(out))

        new = self.log.read_text(encoding="utf-8")[len(log_before):].splitlines()
        self.assertTrue(any(SET_LOG.match(line) for line in new), new)
        self.assertTrue(any(re.match(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} context add .*\bwork\b", line) for line in new),
                        new)


if __name__ == "__main__":
    unittest.main()
