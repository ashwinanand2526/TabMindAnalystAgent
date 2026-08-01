"""Unit tests for the Coder skill and its downstream sandbox_executor path.

Scope
-----
All tests here are OFFLINE — they require no gateway, no LLM, and no
network access.  They exercise:

  1. parse_skill_json  – the JSON parsing helper every skill reply passes
                         through (skills.py)
  2. sandbox.run_python – the subprocess wrapper called by sandbox_executor
                          (sandbox.py)

Style guide: mirrors tests/test_recovery.py — sys.path insert so pytest
finds modules from any working directory, pytest.mark.parametrize for
repeated cases.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

# Allow pytest to find the project modules whether invoked from
# code/tests/ or from code/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from skills import parse_skill_json
from sandbox import run_python


# ── parse_skill_json ─────────────────────────────────────────────────────────

VALID_CODER_REPLIES = [
    # Bare JSON (ideal — what the prompt asks for)
    '{"code": "print(42)", "rationale": "simple print"}',
    # Extra whitespace
    '  {"code": "print(1+1)", "rationale": "arithmetic"}  ',
    # Minified
    '{"code":"x=1\\nprint(x)","rationale":"assign and print"}',
]


@pytest.mark.parametrize("reply", VALID_CODER_REPLIES)
def test_parse_skill_json_returns_dict(reply: str) -> None:
    """parse_skill_json must always return a dict for valid JSON."""
    result = parse_skill_json(reply)
    assert isinstance(result, dict), f"expected dict, got {type(result)}"


@pytest.mark.parametrize("reply", VALID_CODER_REPLIES)
def test_coder_output_has_code_key(reply: str) -> None:
    """Every coder reply must have a 'code' key after parsing."""
    result = parse_skill_json(reply)
    assert "code" in result, f"'code' key missing from parsed output: {result}"


@pytest.mark.parametrize("reply", VALID_CODER_REPLIES)
def test_coder_output_has_rationale_key(reply: str) -> None:
    """Every coder reply must have a 'rationale' key after parsing."""
    result = parse_skill_json(reply)
    assert "rationale" in result, f"'rationale' key missing from parsed output: {result}"


FENCED_REPLIES = [
    # Triple-backtick json fence (common model mistake)
    '```json\n{"code": "print(99)", "rationale": "fenced"}\n```',
    # Triple-backtick no language tag
    '```\n{"code": "print(0)", "rationale": "bare fence"}\n```',
]


@pytest.mark.parametrize("reply", FENCED_REPLIES)
def test_parse_skill_json_strips_markdown_fences(reply: str) -> None:
    """parse_skill_json must strip ``` fences even when the model adds them
    despite being told not to.  This is the fence-stripping fallback in
    skills.py."""
    result = parse_skill_json(reply)
    assert isinstance(result, dict), f"fence stripping failed; got {type(result)}"
    assert "code" in result


# ── sandbox.run_python ───────────────────────────────────────────────────────

def test_sandbox_runs_hello_world() -> None:
    """Basic smoke test: print(42) exits 0 and captures stdout."""
    out = run_python("print(42)")
    assert out["exit_code"] == 0, f"unexpected exit code: {out['exit_code']}"
    assert "42" in out["stdout"], f"stdout missing '42': {out['stdout']!r}"
    assert out["timed_out"] is False


def test_sandbox_arithmetic_correctness() -> None:
    """The sandbox must faithfully execute simple arithmetic."""
    code = "result = sum(range(1, 101))\nprint(result)"
    out = run_python(code)
    assert out["exit_code"] == 0
    assert "5050" in out["stdout"], f"expected 5050 in stdout: {out['stdout']!r}"


def test_sandbox_exit_nonzero_on_exception() -> None:
    """A script that raises an uncaught exception must exit non-zero."""
    out = run_python("raise ValueError('boom')")
    assert out["exit_code"] != 0, "expected non-zero exit code on exception"
    assert "ValueError" in out["stderr"] or "boom" in out["stderr"], (
        f"expected ValueError in stderr: {out['stderr']!r}"
    )


def test_sandbox_timeout() -> None:
    """A script that runs longer than timeout_s must be killed."""
    out = run_python("import time; time.sleep(999)", timeout_s=1)
    assert out["timed_out"] is True, "expected timed_out=True"
    assert out["exit_code"] == -1, f"expected exit_code=-1, got {out['exit_code']}"


def test_sandbox_no_stdout_gives_empty_string() -> None:
    """A script with no print() produces an empty stdout string (not None)."""
    out = run_python("x = 1 + 1  # no print")
    assert out["exit_code"] == 0
    assert isinstance(out["stdout"], str)
    assert out["stdout"].strip() == ""


def test_sandbox_result_shape() -> None:
    """run_python always returns all expected keys regardless of script outcome."""
    required_keys = {
        "exit_code", "stdout", "stdout_truncated",
        "stderr", "stderr_truncated",
        "files_written", "timed_out", "cwd",
    }
    out = run_python("print('shape check')")
    missing = required_keys - set(out.keys())
    assert not missing, f"run_python result missing keys: {missing}"


def test_sandbox_multiline_script() -> None:
    """Multi-line scripts (realistic Coder output) execute correctly."""
    code = (
        "vowels = 'aeiouAEIOU'\n"
        "text = 'The quick brown fox'\n"
        "count = sum(1 for c in text if c in vowels)\n"
        "print(count)\n"
    )
    out = run_python(code)
    assert out["exit_code"] == 0
    assert "5" in out["stdout"], f"expected vowel count 5 in stdout: {out['stdout']!r}"


def test_sandbox_fallback_script_exits_zero() -> None:
    """The Coder's non-computational fallback script must exit 0 so the
    orchestrator marks sandbox_executor as success=True."""
    fallback = "print('(task not suitable for code execution)')"
    out = run_python(fallback)
    assert out["exit_code"] == 0
    assert "not suitable" in out["stdout"]


# ── sandbox_executor skill integration (no gateway) ──────────────────────────

def test_sandbox_executor_missing_code_returns_failure() -> None:
    """When the resolved inputs carry no 'code' key, run_skill for
    sandbox_executor must return success=False with the canonical error
    message that recovery.py looks for."""
    import asyncio
    from skills import SkillRegistry, run_skill

    registry = SkillRegistry()
    skill = registry.get("sandbox_executor")

    # Build a minimal graph_nodes dict that mimics what flow.py passes in:
    # one upstream node whose output dict has no 'code' key.
    fake_nodes = {
        "n:1": {
            "skill": "sandbox_executor",
            "inputs": ["n:0"],
            "metadata": {},
            "status": "running",
        },
        "n:0": {
            "skill": "coder",
            "inputs": [],
            "metadata": {},
            "status": "complete",
            "result": type("R", (), {
                "output": {"rationale": "test"},  # deliberately no 'code' key
            })(),
        },
    }
    # AgentResult is needed so resolve_inputs recognises the upstream result.
    from schemas import AgentResult
    fake_nodes["n:0"]["result"] = AgentResult(
        success=True, agent_name="coder",
        output={"rationale": "test"},  # no 'code'
    )

    result, _prompt = asyncio.run(
        run_skill(skill, "n:1", fake_nodes, "test-session", "dummy query", None)
    )

    assert result.success is False, "expected success=False when code key is absent"
    assert "no code" in (result.error or "").lower(), (
        f"expected 'no code' in error, got: {result.error!r}"
    )
