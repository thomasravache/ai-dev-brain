"""brain.py copiado sozinho, sem a pasta assets/ ao lado, num vault já iniciado (SPEC-0111).
Run: python3 -m unittest discover -s skills/photon-brain/tests -p test_no_assets.py

O vault vem sempre do `init` da skill inteira (brain_support.Sandbox, HOME e XDG_CONFIG_HOME temporários). A cópia
sozinha é o scripts/brain.py copiado para uma pasta temporária cujo pai não tem assets/ (UT-01, UT-03) ou para
dentro do vault, como no uso na nuvem (IT-01). Contrato da seção 6:

    cópia sozinha, vault com brain-config.yml e templates/:
        config, doctor, capture, new-note, relate, index, lint, inbox list, ingest -> como com a skill inteira
    new-note de um tipo sem templates/<tipo>.md no vault:
        exit 2 "modelo <tipo> não encontrado: copie a pasta da skill inteira ou crie templates/<tipo>.md no vault"
    init (vault novo):
        exit 2 "init precisa da pasta da skill inteira (assets/ não encontrada)"
    nenhum traceback por falta de assets/

Mensagens de erro podem ir para stdout ou stderr; o Traceback é procurado nos dois.
"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from brain_support import (
    INIT_LOG_LINE,
    SCRIPT,
    SKILL,
    Sandbox,
    doctor_lines,
    fn,
    output,
)

SKILL_MD = SKILL / "SKILL.md"
CONFIG_MD = SKILL / "references" / "config.md"
ASSET_TEMPLATES = SKILL / "assets" / "templates"
COLLEGE = ("--context", "college=projects/college:College")
MISSING_TEMPLATE = ("modelo lecture não encontrado: copie a pasta da skill inteira ou crie templates/lecture.md "
                    "no vault")
INIT_NEEDS_SKILL = "init precisa da pasta da skill inteira (assets/ não encontrada)"
# o que muda entre dois sandboxes rodados em instantes diferentes: a raiz temporária, o carimbo do nome da captura
# (AAAA-MM-DD-HHMMSS), a hora do log e do created
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}")
CLOCK = re.compile(r"\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2}|Z)?")


def lone_copy(base: Path) -> Path:
    """scripts/brain.py copiado sozinho para <base>/lone/bin/brain.py: nem <base>/lone/assets nem nada da skill."""
    target = base / "lone" / "bin" / "brain.py"
    target.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, target)
    assert not (target.parent.parent / "assets").exists()
    return target


def run_script(box: Sandbox, script: Path, *args, cwd=None, config_home=None):
    """Como Sandbox.run, mas com outro brain.py (a cópia sozinha)."""
    env = box.env()
    env["BRAIN_CONFIG_HOME"] = str(config_home or box.config_home)
    return subprocess.run([sys.executable, str(script), *[str(a) for a in args]], check=False,
                          cwd=cwd or box.root, capture_output=True, text=True, env=env)


def normalized(text: str, box: Sandbox) -> str:
    return CLOCK.sub("<HH:MM>", STAMP.sub("<STAMP>", text.replace(str(box.root), "<ROOT>")))


def vault_state(box: Sandbox) -> dict:
    """Arquivos do vault (caminho e texto normalizados), menos a cópia do script."""
    state = {}
    for path in sorted(box.vault.rglob("*")):
        if path.is_file() and path.suffix != ".py":
            rel = normalized(path.relative_to(box.vault).as_posix(), box)
            state[rel] = normalized(path.read_text(encoding="utf-8"), box)
    return state


# a sequência do UT-01: comandos de leitura e de organização do vault
UT01_COMMANDS = (
    ("config", "--json"),
    ("doctor",),
    ("capture", "ideia sobre grafos", "--context", "college"),
    ("new-note", "--type", "note", "--title", "Primeira nota"),
    ("new-note", "--type", "note", "--title", "Segunda nota", "--context", "college"),
    ("relate", "Primeira nota", "Segunda nota", "--why", "exemplo de"),
    ("index",),
    ("lint",),
    ("inbox", "list", "--json"),
    ("search", "grafos", "--json"),
)


class NoAssetsTestCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, f"exit {result.returncode}, esperado {code}:\n{output(result)}")

    def assertNoTraceback(self, result):
        self.assertNotIn("Traceback", output(result), output(result))


class CharacterizationTest(NoAssetsTestCase):
    def test_whole_skill_init_config_new_note_and_doctor_behave_as_today(self):
        """SPEC-0111:CH-01 — com a skill inteira nada muda (passa antes da mudança)."""
        # SPEC-0111:CH-01
        self.box.vault.mkdir(parents=True)
        out = self.box.init(*COLLEGE)
        self.assertExit(out, 0)
        self.assertRegex((self.box.vault / "log.md").read_text(encoding="utf-8"), INIT_LOG_LINE)
        for template in sorted(ASSET_TEMPLATES.glob("*.md")):
            copied = self.box.vault / "templates" / template.name
            self.assertEqual(copied.read_text(encoding="utf-8"), template.read_text(encoding="utf-8"), template.name)
        parse_yaml = fn("parse_yaml", "SPEC-0111")
        shared = parse_yaml((self.box.vault / "brain-config.yml").read_text(encoding="utf-8"))
        defaults = parse_yaml((SKILL / "assets" / "brain-config.yml").read_text(encoding="utf-8"))
        self.assertEqual(shared["contexts"], {"college": {"folder": "projects/college", "title": "College"}})
        self.assertEqual({k: v for k, v in shared.items() if k != "contexts"},
                         {k: v for k, v in defaults.items() if k != "contexts"})

        data = self.box.config_json()
        self.assertEqual(data["values"]["layout"], defaults["layout"])
        self.assertEqual(data["values"]["para"], defaults["para"])
        self.assertEqual(str(data["values"]["inbox_stale_days"]), str(defaults["inbox_stale_days"]))
        self.assertEqual(data["origins"]["inbox_stale_days"], "vault")

        (self.box.vault / "templates" / "lecture.md").unlink()  # sem o modelo no vault, cai para o da skill
        out = self.box.run("new-note", "--type", "lecture", "--title", "Aula um", "--context", "college")
        self.assertExit(out, 0)
        rel = out.stdout.strip().splitlines()[-1]
        note = (self.box.vault / rel).read_text(encoding="utf-8")
        self.assertTrue(note.startswith("---\n"), note)
        self.assertIn("Aula um", note)

        out = self.box.run("doctor")
        self.assertExit(out, 0)
        self.assertEqual([row for row in doctor_lines(out.stdout) if row[0] == "ERRO"], [], out.stdout)
        self.assertIn("0 erro(s)", out.stdout)


class LoneScriptTest(NoAssetsTestCase):
    def test_lone_copy_runs_read_and_organize_commands_like_the_whole_skill(self):
        """SPEC-0111:UT-01"""
        # SPEC-0111:UT-01
        whole = Sandbox()
        self.addCleanup(whole.cleanup)
        whole.new_vault()
        self.box.new_vault()
        script = lone_copy(self.box.root)
        for args in UT01_COMMANDS:
            expected = whole.run(*args)
            self.assertExit(expected, 0)
            got = run_script(self.box, script, *args)
            self.assertNoTraceback(got)
            self.assertEqual(got.returncode, 0, f"{' '.join(args)} na cópia sozinha:\n{output(got)}")
            self.assertEqual(normalized(got.stdout, self.box), normalized(expected.stdout, whole), " ".join(args))
        self.assertEqual(vault_state(self.box), vault_state(whole))

    def test_lone_copy_new_note_without_the_template_exits_2(self):
        """SPEC-0111:UT-03 — tipo sem templates/<tipo>.md no vault e sem assets/."""
        # SPEC-0111:UT-03
        self.box.new_vault()
        script = lone_copy(self.box.root)
        (self.box.vault / "templates" / "lecture.md").unlink()
        before = sorted(p.relative_to(self.box.vault).as_posix() for p in self.box.vault.rglob("*"))
        out = run_script(self.box, script, "new-note", "--type", "lecture", "--title", "Aula sem modelo")
        self.assertExit(out, 2)
        self.assertIn(MISSING_TEMPLATE, output(out))
        self.assertNoTraceback(out)
        after = sorted(p.relative_to(self.box.vault).as_posix() for p in self.box.vault.rglob("*"))
        self.assertEqual(after, before, "nenhuma nota criada")

    def test_lone_copy_init_of_a_new_vault_exits_2(self):
        """SPEC-0111:UT-03 — o init é o único que precisa dos modelos da skill."""
        # SPEC-0111:UT-03
        script = lone_copy(self.box.root)
        self.box.vault.mkdir(parents=True)
        out = run_script(self.box, script, "init", "--vault", self.box.vault, "--files", self.box.files,
                         "--provider", "local")
        self.assertExit(out, 2)
        self.assertIn(INIT_NEEDS_SKILL, output(out))
        self.assertNoTraceback(out)


class CloudCopyTest(NoAssetsTestCase):
    def test_copy_inside_the_vault_runs_capture_inbox_ingest_move_and_index(self):
        """SPEC-0111:IT-01 — brain.py copiado para dentro do vault, como no uso na nuvem."""
        # SPEC-0111:IT-01
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(*COLLEGE), 0)
        script = self.box.vault / "scripts" / "brain.py"
        script.parent.mkdir()
        shutil.copy2(SCRIPT, script)
        self.assertFalse((self.box.vault / "assets").exists())
        log = self.box.vault / "log.md"
        log_before = log.read_text(encoding="utf-8").splitlines()

        def step(*args):
            out = run_script(self.box, script, *args, cwd=self.box.vault)
            self.assertNoTraceback(out)
            self.assertEqual(out.returncode, 0, f"{' '.join(args)} na cópia do vault:\n{output(out)}")
            return out

        step("capture", "ideia na nuvem", "--context", "college")
        (self.box.vault / "inbox" / "aula.pdf").write_bytes(b"%PDF-1.4 aula de grafos")
        items = json.loads(step("inbox", "list", "--json").stdout)["items"]
        paths = [item["path"] for item in items]
        self.assertIn("inbox/aula.pdf", paths)
        self.assertTrue(any(re.match(r"^inbox/\d{4}-\d{2}-\d{2}-\d{6}-ideia-na-nuvem\.md$", p) for p in paths), paths)
        data = json.loads(step("ingest", "inbox/aula.pdf", "--move", "--context", "college", "--json").stdout)
        self.assertFalse((self.box.vault / "inbox" / "aula.pdf").exists())
        self.assertTrue((self.box.files / data["file"]).is_file())
        step("index")

        new_lines = log.read_text(encoding="utf-8").splitlines()[len(log_before):]
        for command in ("capture", "ingest", "index"):
            self.assertTrue(any(re.match(rf"^- \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} {command} ", line)
                                for line in new_lines), f"log.md sem linha de {command}: {new_lines}")


def paragraphs(path: Path) -> list:
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0111)")
    return [p for p in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")) if p.strip()]


class DocumentationTest(unittest.TestCase):
    def check(self, path: Path):
        found = paragraphs(path)
        minimal = [p for p in found if "scripts/brain.py" in p
                   and re.search(r"c[óo]pia m[íi]nima|minimal copy", p, re.IGNORECASE)
                   and re.search(r"vault j[áa] iniciado|already (initialized|set up)", p, re.IGNORECASE)]
        self.assertTrue(minimal, f"{path.name}: falta dizer que a cópia mínima é scripts/brain.py com um vault já "
                                 "iniciado (SPEC-0111)")
        whole = [p for p in found if re.search(r"\binit\b", p)
                 and re.search(r"pasta da skill inteira|whole skill folder", p, re.IGNORECASE)]
        self.assertTrue(whole, f"{path.name}: falta dizer que o init precisa da pasta da skill inteira (SPEC-0111)")

    def test_config_md_describes_the_minimal_and_the_whole_copy(self):
        """SPEC-0111:UT-04"""
        # SPEC-0111:UT-04
        self.check(CONFIG_MD)

    def test_skill_md_describes_the_minimal_and_the_whole_copy(self):
        """SPEC-0111:UT-04"""
        # SPEC-0111:UT-04
        self.check(SKILL_MD)


if __name__ == "__main__":
    unittest.main()
