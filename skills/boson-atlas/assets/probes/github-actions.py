#!/usr/bin/env python3
"""github-actions probe adapter of the boson-atlas (SPEC-0106, ADR-0023, ADR-0025), contract probe@2 (SPEC-0096).

Usage: python3 github-actions.py --describe     -> the capabilities (pipeline: runs, on a deployment, input change)
       python3 github-actions.py < input.json   -> reads the probe@2 input on stdin, prints the probe@2 output

The runs of the CI for one commit in each code repository of the service (target.change, built by the core from
delivery.code_repositories). Read only: the one external process is the machine's `gh`, run with an argv list (never a
shell), stdin closed and a timeout, built only from target.change and from a closed list (SPEC-0106, section 6):
    gh api -X GET repos/<owner>/<repo>/actions/runs -f head_sha=<commit> -f per_page=100   (one per repository, up
        to 10 repositories; the others stay out and the output is truncated)
Nothing else is ever called: no other path or method, no --paginate, --input, workflow, run or rerun. The commit must
be 40 lower-case hexadecimal characters and each repository <owner>/<repo> by a closed rule, checked before any call.
`gh` gets only the environment the core gives the adapter (GH_TOKEN only when declared in credentials). A run never
carries its title, actor, branch or pull requests; the URL leaves without user, query or fragment. A repository that
answers 404 becomes {"repository", "found": false}; any other error fails the whole run with a fixed message, never
the stderr of gh. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

CONTRACT = "probe@2"
ADAPTER = "github-actions"
CAPABILITY = "pipeline"
VERB = "runs"
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": [VERB], "targets": ["deployment"], "access": [],
                                          "inputs": ["change"]}}}
PER_PAGE = "100"
MAX_REPOSITORIES = 10
MAX_LINES = 2000
PROCESS_TIMEOUT = 30  # seconds for one gh process
TEXT_MAX = 300
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}\Z")
REPOSITORY_RE = re.compile(r"^[a-z0-9_.-]+/[a-z0-9_.-]+\Z")
TIMEOUT_RE = re.compile(r"i/o timeout|timed out|deadline exceeded|timeout", re.IGNORECASE)
# the contract messages (SPEC-0106, section 6)
NO_GH = "gh não encontrado"
NO_AUTH = "sem autenticação no GitHub"
FORBIDDEN = "sem permissão (403)"
RATE_LIMIT = "limite de requisições do GitHub"
TIMEOUT = "timeout"
INVALID_ANSWER = "resposta inválida do gh"
REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
NOT_FOUND = "não encontrado"  # internal: a 404 of one repository (never printed)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def repository_ok(value) -> bool:
    """<owner>/<repo> in lower case, each part without a leading "-" or "." and no "..": never an option or a path."""
    if not isinstance(value, str) or not REPOSITORY_RE.match(value) or ".." in value:
        return False
    return all(part and part[0] not in "-." for part in value.split("/"))


def check_input(data):
    """(commit, repositories, truncated, lines) of a probe@2 input, or ProbeError (INVALID_INPUT, REFUSED). Nothing here
    calls gh."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT or data.get("capability") != CAPABILITY:
        raise ProbeError(INVALID_INPUT)
    if data.get("verb") != VERB:
        raise ProbeError(REFUSED)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    change = target.get("change")
    if not isinstance(change, dict):
        raise ProbeError(INVALID_INPUT)
    commit, repositories = change.get("commit"), change.get("repositories")
    if not isinstance(commit, str) or not COMMIT_RE.match(commit):
        raise ProbeError(INVALID_INPUT)
    if not isinstance(repositories, list) or not repositories or not all(repository_ok(r) for r in repositories):
        raise ProbeError(INVALID_INPUT)
    lines = limits.get("lines")
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise ProbeError(INVALID_INPUT)
    unique = list(dict.fromkeys(repositories))
    return commit, unique[:MAX_REPOSITORIES], len(unique) > MAX_REPOSITORIES, min(lines, MAX_LINES)


# ---------------------------------------------------------------- gh


def classify(text: str) -> str:
    """The fixed message (or NOT_FOUND) of a failed gh: never its text (it may quote the token)."""
    if re.search(r"rate limit", text, re.IGNORECASE):
        return RATE_LIMIT
    if "HTTP 404" in text:
        return NOT_FOUND
    if "HTTP 401" in text or "Bad credentials" in text or "gh auth login" in text:
        return NO_AUTH
    if "HTTP 403" in text:
        return FORBIDDEN
    if TIMEOUT_RE.search(text):
        return TIMEOUT
    return INVALID_ANSWER


class Gh:
    """The only door to gh: `api -X GET repos/<owner>/<repo>/actions/runs` with head_sha and per_page, once per
    repository."""

    def __init__(self, commit):
        self.commit = commit
        self.executable = None
        self.called = set()

    def runs(self, repository):
        """The answer of the API for one repository, or None for a 404."""
        if not repository_ok(repository) or repository in self.called:
            raise ProbeError(REFUSED)
        self.called.add(repository)
        argv = ["api", "-X", "GET", f"repos/{repository}/actions/runs", "-f", f"head_sha={self.commit}", "-f",
                f"per_page={PER_PAGE}"]
        if self.executable is None:
            self.executable = shutil.which("gh") or ""
        if not self.executable:
            raise ProbeError(NO_GH)
        environment = dict(os.environ, GH_PROMPT_DISABLED="1")
        try:
            proc = subprocess.run([self.executable, *argv], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT, check=False,
                                  env=environment)
        except subprocess.TimeoutExpired:
            raise ProbeError(TIMEOUT) from None
        except OSError:
            raise ProbeError(NO_GH) from None
        if proc.returncode != 0:
            reason = classify(f"{proc.stderr or ''}\n{proc.stdout or ''}")
            if reason == NOT_FOUND:
                return None
            raise ProbeError(reason)
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise ProbeError(INVALID_ANSWER) from None
        if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            raise ProbeError(INVALID_ANSWER)
        if not all(isinstance(run, dict) for run in data["workflow_runs"]):
            raise ProbeError(INVALID_ANSWER)
        return data


# ---------------------------------------------------------------- helpers


def text(value) -> str:
    return value.strip()[:TEXT_MAX] if isinstance(value, str) else ""


def parse_ts(value):
    """An RFC 3339 time ("2026-11-24T10:00:00Z", with or without fraction or offset) -> aware datetime, or None."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$", value.strip())
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    zone = match.group(2) or "Z"
    if zone == "Z":
        return moment.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    return moment.replace(tzinfo=timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))))


def clean_url(value) -> str:
    """scheme://host[:port]/path of an http(s) URL: without user, password, query or fragment; "" otherwise."""
    if not isinstance(value, str) or any(c.isspace() for c in value.strip()):
        return ""
    try:
        parts = urllib.parse.urlsplit(value.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not host:
        return ""
    netloc = host + (f":{port}" if port else "")
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def run_item(repository, run):
    status = text(run.get("status"))
    done = status == "completed"
    attempt = run.get("run_attempt")
    started = text(run.get("run_started_at")) or text(run.get("created_at"))
    duration = None
    if done:
        begin, end = parse_ts(started), parse_ts(run.get("updated_at"))
        if begin and end and end >= begin:
            duration = int((end - begin).total_seconds())
    return {"repository": repository, "found": True, "workflow": text(run.get("name")), "path": text(run.get("path")),
            "event": text(run.get("event")), "status": status,
            "conclusion": text(run.get("conclusion")) if done else "",
            "attempt": attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else 1,
            "started_at": started, "duration_seconds": duration, "url": clean_url(run.get("html_url"))}


def run_runs(gh, repositories, lines):
    items, truncated = [], False
    for repository in repositories:
        data = gh.runs(repository)
        if data is None:
            items.append({"repository": repository, "found": False})
            continue
        runs = data["workflow_runs"]
        total = data.get("total_count")
        if isinstance(total, int) and not isinstance(total, bool) and total > len(runs):
            truncated = True
        items += [run_item(repository, run) for run in runs]
    items.sort(key=lambda i: (i["repository"], i.get("started_at", ""), i.get("url", "")))
    if len(items) > lines:
        truncated = True
    return items[:lines], truncated


# ---------------------------------------------------------------- main


def answer(data, status, items, truncated, message=None):
    verb = data.get("verb") if isinstance(data, dict) else None
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY,
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else VERB, "status": status,
              "items": items, "truncated": truncated}
    if message:
        output["message"] = message
    return output


def probe(data):
    try:
        commit, repositories, cut, lines = check_input(data)
        items, truncated = run_runs(Gh(commit), repositories, lines)
    except ProbeError as error:
        return answer(data, "error", [], False, str(error))
    except (AttributeError, TypeError, ValueError, KeyError):
        # a shape the checks did not foresee: still a fixed message, never a traceback
        return answer(data, "error", [], False, INVALID_ANSWER)
    return answer(data, "ok", items, truncated or cut)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: github-actions.py --describe | github-actions.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
