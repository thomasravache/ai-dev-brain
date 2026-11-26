#!/usr/bin/env python3
"""suite probe adapter of the boson-atlas (SPEC-0103, ADR-0023, ADR-0026 rule 4), contract probe@2 (SPEC-0096).

Usage: python3 suite.py --journeys-file <journeys.json> --describe   -> the capability (functional: run)
       python3 suite.py --journeys-file <journeys.json> < input.json  -> runs the requested journeys, prints the output

The atlas says WHICH journeys count for a service (target.journeys, curated by a person); the journeys file of this
machine says HOW to run each one (references/probes/suite.md). The file is validated whole before any journey runs:
    {"journeys": {"<id>": {"command": ["<name in PATH or absolute path>", ...], "cwd": "<absolute>",
                           "timeout": <1..300, default 120>, "credentials": ["<ENV_NAME>", ...]}}}
For each id of target.journeys, in order: no entry -> skipped; a credential of the journey missing from this
adapter's environment -> skipped; executable not found -> skipped; else the suite runs with an argv list (never a
shell), in its cwd (or a temporary folder), in its own process group, with the journey's timeout (the whole group is
ended when it expires). Exit 0 -> passed, 77 -> skipped, any other -> failed with the "ATLAS-FAILED-STEP: " lines of
its stdout (at most 5, 200 characters each). No other line of a suite ever leaves this adapter. The suite environment
is the minimum of the probes, the credentials OF THAT JOURNEY and ATLAS_SERVICE, ATLAS_ENVIRONMENT, ATLAS_JOURNEY and
ATLAS_BASE_URL. Errors leave with exit 0 and status "error" with a short message, never a value of the file. The
core (atlas.py probe) masks the output again. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

CONTRACT = "probe@2"
ADAPTER = "suite"
CAPABILITY = "functional"
VERB = "run"
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER, "capabilities": {CAPABILITY: {
    "verbs": [VERB], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
FILE_KEYS = ("journeys",)
JOURNEY_KEYS = ("command", "cwd", "timeout", "credentials")
TIMEOUT_DEFAULT, TIMEOUT_MAX = 120, 300
FILE_MAX_BYTES = 1024 * 1024  # the most a journeys file may have
OUTPUT_MAX_BYTES = 1024 * 1024  # the most read from the stdout of one suite; the rest is discarded
STEP_PREFIX = "ATLAS-FAILED-STEP: "
STEPS_MAX, STEP_CHARS = 5, 200
SKIP_EXIT = 77
# the same names as PROBE_BASE_ENV of the core: the only variables of this adapter a suite may get
BASE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TZ", "TMPDIR",
            "TMP", "TEMP", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "__CF_USER_TEXT_ENCODING")
NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")  # the simple name rule of the atlas
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*\Z")
# the contract messages (section 6 of SPEC-0103)
NO_FILE = "sem arquivo de jornadas (--journeys-file)"
INVALID_FILE = "arquivo de jornadas inválido: "
INVALID_INPUT = "entrada inválida"
NO_COMMAND = "jornada sem comando neste arquivo de jornadas"
NOT_RECEIVED = "credencial não recebida: {name}"
NOT_FOUND = "comando da suíte não encontrado"
SKIPPED_BY_SUITE = "a suíte pulou a jornada"
TIMED_OUT = "tempo esgotado ({seconds}s)"
EXITED = "a suíte saiu com {code}"


class ProbeError(Exception):
    """An error with a short fixed message: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- the journeys file


def _journey_problems(jid, entry) -> list:
    where = f"journeys.{jid}"
    if not isinstance(entry, dict):
        return [f"{where} — precisa ser um objeto {{command, cwd, timeout, credentials}}"]
    problems = [f"{where} — chave fora do contrato (aceitas: {', '.join(JOURNEY_KEYS)})"
                for key in entry if key not in JOURNEY_KEYS]
    command = entry.get("command")
    if "command" not in entry:
        problems.append(f"{where}.command — obrigatório")
    elif not (isinstance(command, list) and command and all(isinstance(a, str) and a for a in command)):
        problems.append(f"{where}.command — precisa ser uma lista não vazia de textos (sem shell)")
    elif not ((os.path.isabs(command[0]) or ("/" not in command[0] and "\\" not in command[0]))
              and not command[0].startswith("-")):
        problems.append(f"{where}.command — o executável precisa ser um nome do PATH ou um caminho absoluto")
    if "cwd" in entry and not (isinstance(entry["cwd"], str) and os.path.isabs(entry["cwd"])):
        problems.append(f"{where}.cwd — precisa ser um caminho absoluto")
    timeout = entry.get("timeout")
    if "timeout" in entry and (isinstance(timeout, bool) or not isinstance(timeout, int)
                               or not 1 <= timeout <= TIMEOUT_MAX):
        problems.append(f"{where}.timeout — precisa ser um inteiro de 1 a {TIMEOUT_MAX} (segundos)")
    credentials = entry.get("credentials")
    if "credentials" in entry and not (isinstance(credentials, list)
                                       and all(isinstance(n, str) and ENV_NAME_RE.match(n) for n in credentials)):
        problems.append(f"{where}.credentials — precisa ser uma lista de nomes de variável (A-Z, 0-9, _)")
    return problems


def validate_journeys(data) -> list:
    """Problems of a journeys file, each "<campo> — <motivo>" and never the value; [] = valid."""
    if not isinstance(data, dict):
        return ["arquivo — precisa ser um objeto {\"journeys\": {...}}"]
    problems = [f"arquivo — chave fora do contrato (aceita: {', '.join(FILE_KEYS)})" for key in data
                if key not in FILE_KEYS]
    journeys = data.get("journeys")
    if "journeys" not in data:
        problems.append("journeys — obrigatório")
    elif not isinstance(journeys, dict):
        problems.append("journeys — precisa ser um mapa <jornada>: {command, ...}")
    else:
        for jid, entry in journeys.items():
            if not isinstance(jid, str) or not NAME_RE.match(jid):
                problems.append("journeys — um id de jornada fora da regra de nome (letras, dígitos, . _ -, sem "
                                "espaço)")
                continue
            problems += _journey_problems(jid, entry)
    return problems


def read_journeys(path) -> dict:
    """The journeys map of the file at `path`, validated whole; ProbeError with the contract message otherwise."""
    if path is None:
        raise ProbeError(NO_FILE)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(FILE_MAX_BYTES + 1)
    except FileNotFoundError:
        raise ProbeError(INVALID_FILE + "--journeys-file — arquivo não encontrado") from None
    except OSError:
        raise ProbeError(INVALID_FILE + "--journeys-file — não consegui ler o arquivo") from None
    if len(raw) > FILE_MAX_BYTES:
        raise ProbeError(INVALID_FILE + "arquivo — acima de 1 MB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ProbeError(INVALID_FILE + "arquivo — não é JSON válido") from None
    problems = validate_journeys(data)
    if problems:
        raise ProbeError(INVALID_FILE + problems[0])
    return data["journeys"]


# ---------------------------------------------------------------- input


def check_input(data) -> tuple:
    """(service, environment, base_url, journeys) of a probe@2 functional input, or ProbeError(INVALID_INPUT)."""
    if not (isinstance(data, dict) and data.get("contract") == CONTRACT and data.get("capability") == CAPABILITY
            and data.get("verb") == VERB and isinstance(data.get("target"), dict)):
        raise ProbeError(INVALID_INPUT)
    target = data["target"]
    journeys = target.get("journeys")
    urls = target.get("urls")
    base_url = urls.get("base_url") if isinstance(urls, dict) else None
    if (not all(isinstance(target.get(k), str) and target[k] for k in ("service", "environment"))
            or not (isinstance(journeys, list) and all(isinstance(j, str) and j for j in journeys))
            or (base_url is not None and not isinstance(base_url, str))):
        raise ProbeError(INVALID_INPUT)
    return target["service"], target["environment"], base_url, list(dict.fromkeys(journeys))


# ---------------------------------------------------------------- one journey


def _executable(command0, environment) -> bool:
    if os.path.isabs(command0):
        return os.path.isfile(command0) and os.access(command0, os.X_OK)
    return shutil.which(command0, path=environment.get("PATH", os.defpath)) is not None


def _end_group(proc) -> None:
    """Ends the suite and everything it started (its process group on POSIX)."""
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass


def _run(command, cwd, environment, timeout) -> tuple:
    """(exit code or None on timeout, stdout text up to OUTPUT_MAX_BYTES) of one suite: argv list, no shell, its own
    process group, stdin and stderr closed to it. FileNotFoundError/PermissionError when it cannot start."""
    proc = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, shell=False, start_new_session=os.name != "nt")
    kept = bytearray()

    def pump():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                room = OUTPUT_MAX_BYTES - len(kept)
                if room > 0:
                    kept.extend(chunk[:room])
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
    finally:
        if proc.poll() is None:
            _end_group(proc)
    if code is not None:
        reader.join(timeout=2)
    _end_group(proc)  # whatever the suite left running ends with it
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    reader.join(timeout=5)
    try:
        proc.stdout.close()
    except OSError:
        pass
    return code, kept.decode("utf-8", errors="replace")


def failed_steps(text) -> list:
    steps = []
    for line in text.splitlines():
        if line.startswith(STEP_PREFIX):
            steps.append(line[len(STEP_PREFIX):].rstrip("\r")[:STEP_CHARS])
            if len(steps) == STEPS_MAX:
                break
    return steps


def journey_item(jid, result, started, steps=()) -> dict:
    return {"journey": jid, "result": result, "duration_seconds": round(max(time.monotonic() - started, 0.0), 3),
            "failed_steps": list(steps)}


def run_journey(jid, entry, service, environment, base_url) -> dict:
    started = time.monotonic()
    if entry is None:
        return journey_item(jid, "skipped", started, [NO_COMMAND])
    credentials = entry.get("credentials") or []
    for name in credentials:
        if name not in os.environ:
            return journey_item(jid, "skipped", started, [NOT_RECEIVED.format(name=name)])
    suite_env = {name: os.environ[name] for name in BASE_ENV if name in os.environ}
    suite_env.update({name: os.environ[name] for name in credentials})
    suite_env.update({"ATLAS_SERVICE": service, "ATLAS_ENVIRONMENT": environment, "ATLAS_JOURNEY": jid})
    if base_url is not None:
        suite_env["ATLAS_BASE_URL"] = base_url
    command = list(entry["command"])
    if not _executable(command[0], suite_env):
        return journey_item(jid, "skipped", started, [NOT_FOUND])
    timeout = entry.get("timeout", TIMEOUT_DEFAULT)
    with tempfile.TemporaryDirectory(prefix="atlas-suite-") as tmp:
        try:
            code, text = _run(command, entry.get("cwd") or tmp, suite_env, timeout)
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            return journey_item(jid, "skipped", started, [NOT_FOUND])
    if code is None:
        return journey_item(jid, "failed", started, [TIMED_OUT.format(seconds=timeout)])
    if code == 0:
        return journey_item(jid, "passed", started)
    if code == SKIP_EXIT:
        return journey_item(jid, "skipped", started, [SKIPPED_BY_SUITE])
    return journey_item(jid, "failed", started, failed_steps(text) or [EXITED.format(code=code)])


# ---------------------------------------------------------------- main


def answer(status, items, message=None) -> dict:
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY, "verb": VERB, "status": status,
              "items": items, "truncated": False}
    if message:
        output["message"] = message
    return output


def probe(data, journeys_file) -> dict:
    try:
        service, environment, base_url, requested = check_input(data)
        journeys = read_journeys(journeys_file)
    except ProbeError as error:
        return answer("error", [], str(error))
    # only the requested ids run; a journey of the file that was not requested never runs
    items = [run_journey(jid, journeys.get(jid), service, environment, base_url) for jid in requested]
    return answer("ok", items)


def parse_args(argv) -> tuple:
    """(journeys_file or None, describe) of the command line; anything else = None."""
    journeys_file, describe, index = None, False, 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--describe":
            describe = True
        elif arg == "--journeys-file" and index + 1 < len(argv):
            journeys_file = argv[index + 1]
            index += 1
        elif arg.startswith("--journeys-file="):
            journeys_file = arg.split("=", 1)[1]
        else:
            return None
        index += 1
    return journeys_file, describe


def main(argv):
    parsed = parse_args(argv)
    if parsed is None:
        print("uso: suite.py --journeys-file <journeys.json> [--describe] < entrada.json", file=sys.stderr)
        return 2
    journeys_file, describe = parsed
    if describe:
        print(json.dumps(DESCRIBE))
        return 0
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data, journeys_file), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
