# Session 8 Assignment — Implement the Coder Skill

## What you ship

Two additions to the codebase — nothing else:

| File | Action |
|---|---|
| `code/prompts/coder.md` | Replace the STUB with your prompt. |
| `code/tests/test_coder.py` | New test file with at least 3 unit tests. |

Everything else — `agent_config.yaml`, `flow.py`, `skills.py`,
`sandbox.py`, `recovery.py` — is already wired correctly. You write
only the prompt and the tests.

---

## How the orchestrator uses your Coder

When the Planner emits a `coder` node, the orchestrator:

1. Renders your `coder.md` system prompt with the INPUTS block
   (upstream findings, user query, FAISS memory hits).
2. Sends it to the LLM gateway at `temperature=0.2`, `max_tokens=1500`.
3. Parses the model's reply as a JSON object via `parse_skill_json`.
4. Because `agent_config.yaml` lists `internal_successors: [sandbox_executor]`,
   it **automatically** appends a `sandbox_executor` node — you do **not**
   need the Coder to emit `successors`.
5. `sandbox_executor` reads `output["code"]` from your Coder node and
   calls `sandbox.run_python(code)` directly (no LLM round-trip).
6. The result dict `{exit_code, stdout, stderr, timed_out, files_written}`
   flows downstream to the Formatter as that node's INPUTS.

```
[Planner]
    │  emits coder node
    ▼
[Coder]  ── internal_successor ──▶  [SandboxExecutor]
    output: {"code": "...", "rationale": "..."}      │ calls sandbox.run_python(code)
                                                     ▼
                                              [Formatter]  →  final_answer
```

### Output contract

Your prompt MUST cause the model to emit exactly this JSON shape —
no markdown fences, no wrapping prose:

```json
{"code": "<complete python source>", "rationale": "<one short line>"}
```

If `output["code"]` is absent or empty, `sandbox_executor` returns:

```
AgentResult(success=False, error="no code in upstream coder output")
```

and the orchestrator queues a recovery Planner (see `recovery.py`).

---

## Acceptance criteria

Run these five queries end-to-end and verify the outputs match.

### 1. Basic arithmetic

```bash
cd code
uv run python flow.py "Write Python to compute the sum of integers from 1 through 100 and print it."
```

**Expected**: Final answer contains `5050`.

### 2. String manipulation

```bash
uv run python flow.py "Write Python to count the vowels in the string 'The quick brown fox' and print the count."
```

**Expected**: Final answer contains `5` (e, u, i, o, o).

### 3. Fibonacci sequence

```bash
uv run python flow.py "Write Python to print the first 10 Fibonacci numbers."
```

**Expected**: Final answer contains the sequence starting `0, 1, 1, 2, 3, 5 …`

### 4. Graceful non-computational task

```bash
uv run python flow.py "Using the coder skill, tell me what the capital of France is."
```

**Expected**: Coder emits the fallback script (`print('(task not suitable for code
execution)')`); SandboxExecutor exits 0; Formatter answers gracefully — no crash,
no empty final answer.

### 5. Replay check

After any of the above runs, note the session id printed in the banner line, then:

```bash
uv run python replay.py <sid>
```

Inspect the `coder` node's `prompt_sent` field. Your system prompt must appear
verbatim at the top of that field, followed by the QUESTION / INPUTS block the
orchestrator injected.

---

## Tests to write (`code/tests/test_coder.py`)

Add **at least three** of the following — choose the ones that give you the most
confidence. All must run **offline** (no gateway, no LLM).

| Test | What to assert |
|---|---|
| `test_coder_output_has_code_key` | `parse_skill_json` on a literal coder-shaped reply string returns a dict with key `"code"`. |
| `test_coder_output_has_rationale_key` | Same dict has key `"rationale"`. |
| `test_sandbox_runs_hello_world` | `sandbox.run_python("print(42)")` returns `exit_code=0` and `stdout` containing `"42"`. |
| `test_sandbox_missing_code_returns_error` | Calling `run_skill` for `sandbox_executor` with resolved inputs that contain no `"code"` key returns `success=False` with error text containing `"no code"`. |
| `test_sandbox_timeout` | `sandbox.run_python("import time; time.sleep(999)", timeout_s=1)` returns `timed_out=True` and `exit_code=-1`. |
| `test_sandbox_exit_nonzero_on_exception` | `sandbox.run_python("raise ValueError('boom')")` returns `exit_code != 0`. |
| `test_parse_skill_json_strips_fences` | Feed `parse_skill_json` a string with triple-backtick fences around valid JSON; assert it returns the correct dict. |

Use `tests/test_recovery.py` as a style guide:

- Add `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` so
  pytest finds the modules whether run from `tests/` or `code/`.
- Use `pytest.mark.parametrize` for repeated cases (e.g. multiple valid JSON
  strings that should parse cleanly).
- Keep tests focused and fast — none of them should start the gateway or call
  an LLM.

---

## Grading rubric

| Criterion | Marks |
|---|---|
| `coder.md` replaces the STUB; non-trivial (> 10 lines); has role, procedure, output schema, safety rules | 20 |
| Acceptance query 1 (arithmetic — 5050) passes end-to-end | 15 |
| Acceptance query 2 (string manipulation — vowel count) passes | 15 |
| Acceptance query 3 (Fibonacci) passes | 15 |
| Acceptance query 4 (graceful non-computational fallback) passes | 10 |
| `test_coder.py` has ≥ 3 tests; all pass via `pytest tests/` | 15 |
| Replay (query 5) shows your prompt verbatim in `prompt_sent` | 10 |
| **Total** | **100** |

---

## What NOT to touch

- `agent_config.yaml` — the Coder wiring (`internal_successors`,
  `temperature`, `max_tokens`) is already correct.
- `flow.py`, `skills.py`, `recovery.py`, `sandbox.py`, `schemas.py` —
  orchestrator internals.
- `perception.py`, `decision.py`, `action.py`, `memory.py`,
  `vector_index.py`, `mcp_server.py` — S7 carryover; byte-identical
  contract must be preserved.
- `gateway/` — treat as a black-box service. If you find a real bug, open
  an issue; do not patch it inside your assignment.
- Any existing test in `tests/test_recovery.py`.

---

## Hints

**Temperature 0.2** means the LLM is nearly deterministic. Your prompt
wording is load-bearing — a vague instruction produces a vague script.

**Sandbox environment** strips all env vars except `PATH`, `HOME`, `LANG`,
`LC_ALL`, `LC_CTYPE`. Third-party packages that depend on env vars will
silently fail. Keep generated code to stdlib.

**Isolation**: `sandbox.run_python` writes the code to a temp directory as
`main.py` and runs `sys.executable main.py`. The script cannot import any
project modules (`skills`, `flow`, `schemas`, …). It is truly isolated.

**No stdout = failure**: If the generated script never calls `print()`, the
Formatter receives an empty `stdout` string and cannot compose a meaningful
answer. Your prompt must enforce that the script prints its result.

**Debugging a bad run**: Sessions land in `code/state/sessions/<sid>/`. Use
`replay.py <sid>` to inspect every node's exact prompt, output, and timing
without re-running the query.

**Recovery path**: If Coder emits invalid JSON (no `code` key), the
orchestrator calls `plan_recovery` → `classify_failure` → `"upstream_failure"`
→ queues a new Planner. One re-plan is allowed per branch before the cap
fires and the final answer reflects missing data. This is normal behaviour;
your job is to write a prompt that avoids triggering it.
