# proofica

Minimal Python starter for a LangGraph agent that calls Amazon Bedrock through the AWS `Converse` API, using Meta Llama 4 Maverick as the default model target.

## What this starter includes

- `src/bedrock_langgraph_agent/`: the LangGraph code
- `.env.example`: local environment variables for AWS/profile selection
- `config/agent.example.yaml`: non-secret runtime settings kept outside the code
- `examples/checkout_form.html`: draft HTML page used by the page-object workflow
- `examples/checkout_journey.ndjson`: sample GTM-like NDJSON journey used by the phase-1 planner

The Bedrock call is made with `boto3` and `bedrock-runtime.converse(...)`, so it stays on Amazon's API surface instead of using a model-specific SDK.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp config/agent.example.yaml config/agent.local.yaml
```

Then make sure one of these is true:

- `AWS_PROFILE` in `.env` points to a profile that already has Bedrock access.
- Or you provide the standard AWS credential variables locally.

Your IAM identity also needs Bedrock invocation access for the selected model, for example `bedrock:InvokeModel*`.

## Run

```bash
python -m bedrock_langgraph_agent.main --prompt "Hello from LangGraph on Amazon Bedrock."
```

If you omit `--prompt`, the app uses `app.default_user_prompt` from `config/agent.local.yaml`.

## Generate A Page Object

This repo also includes a more LangGraph-style page-object workflow:

- The HTML input is parsed deterministically.
- The deterministic policy lives in typed Python modules, not a YAML rule file.
- Graph state, node logic, prompt construction, and graph wiring are split into separate modules.
- The verifier checks the generated Selenium page object.
- If verification fails, the verifier feedback is sent back into the LLM and the graph retries until it passes or reaches the maximum attempt count.

Example:

```bash
python -m bedrock_langgraph_agent.main \
  --html-input examples/checkout_form.html \
  --page-object-output output/checkout_form_page.py \
  --max-attempts 3
```

If you omit `--page-object-output`, the verified page object is printed to stdout.
The workflow always writes a detailed JSON trace with every node entry, node exit, LLM call, and graph transition.
By default, traces are stored under `logs/page_object_traces/`.
If you pass `--trace-output`, that path overrides the default trace location.

## Plan A Journey From NDJSON

Phase 1 of the larger workflow is now in place:

- one NDJSON journey per run
- deterministic journey normalization and planning
- timestamped run output directory under `output/<timestamp>/`
- optional authentication checkpoint scaffolding

Example:

```bash
bedrock-langgraph-agent --journey-events examples/checkout_journey.ndjson
```

That command creates a run directory like:

```text
output/20260325T160000Z/
```

and writes:

- `input/<source file>.ndjson`
- `journey/normalized_events.json`
- `journey/journey_spec.json`
- `journey/auth_checkpoint.json`
- `run_manifest.json`
- `logs/journey_planning_trace.json`

## Capture Pages From A Planned Run

Phase 2 adds a Selenium-first capture workflow:

- loads the run directory produced by phase 1
- optionally pauses for manual login when the auth checkpoint requires it
- captures one snapshot per unique page URL in the journey
- writes HTML, screenshots, actionable element inventories, and a capture manifest

Example:

```bash
bedrock-langgraph-agent --capture-run output/20260325T160000Z
```

If the journey requires authentication, the command opens Chrome, waits for you to complete login manually, and continues after you press Enter in the terminal.

The capture step writes:

- `pages/01_<page-name>/snapshot.html`
- `pages/01_<page-name>/screenshot.png`
- `pages/01_<page-name>/actionable_elements.json`
- `pages/page_capture_manifest.json`
- `logs/page_capture_trace.json`

## Generate Page Objects From Captured Pages

Phase 3 now consumes the captured browser snapshots instead of a standalone HTML file.

Example:

```bash
bedrock-langgraph-agent --generate-page-objects-run output/20260325T235606Z
```

That command:

- loads `pages/page_capture_manifest.json`
- generates one verified page object per captured snapshot through Bedrock
- writes Python files into `page_objects/`
- writes one trace per page object under `logs/page_object_traces/`
- writes `page_objects/page_object_manifest.json`
- updates `run_manifest.json`

## Verify Page Objects Against Captured Snapshots

Phase 4 runs the generated page objects against the captured `snapshot.html` pages in a browser-safe local context.
If runtime verification fails, the detailed browser-side feedback is sent back through the page-object generation loop and the artifact is repaired and retried.

Example:

```bash
bedrock-langgraph-agent --verify-page-objects-run output/20260325T235606Z
```

That command:

- loads `page_objects/page_object_manifest.json`
- opens each captured `snapshot.html` page in Chrome
- verifies the generated locators and actions against the page
- repairs the page object through Bedrock if runtime verification fails
- writes `page_objects/page_object_runtime_verification_manifest.json`
- writes `logs/page_object_runtime_verification_trace.json`
- updates `run_manifest.json`

## Generate A Pytest Selenium Test From The Verified Run

Phase 5 turns the journey spec plus the runtime-verified page objects into a deterministic
`pytest` Selenium test under the same run directory.

Example:

```bash
bedrock-langgraph-agent --generate-tests-run output/20260325T235606Z
```

That command:

- loads `journey/journey_spec.json`
- loads `page_objects/page_object_manifest.json`
- loads `page_objects/page_object_runtime_verification_manifest.json`
- builds a deterministic test plan from the journey actions and the runtime-verified page-object methods
- falls back to runtime smoke actions when the journey has no actionable steps for a page
- writes `tests/test_generated_journey.py`
- writes `tests/generated_journey_plan.json`
- writes `tests/test_authoring_manifest.json`
- writes `logs/test_authoring_trace.json`
- updates `run_manifest.json`

## Execute And Repair The Generated Pytest Test

Phase 6 executes the generated pytest Selenium test, writes a normalized execution report,
and only sends the test through Bedrock repair when the failure looks like a code issue rather
than an environment problem.

If you added this phase after your original install, refresh the environment first:

```bash
pip install -e .
```

Example:

```bash
bedrock-langgraph-agent --execute-tests-run output/20260325T235606Z
```

That command:

- loads `tests/test_generated_journey.py`
- runs `pytest` against the generated test file
- writes `tests/test_execution_report.json`
- writes `tests/test_execution_manifest.json`
- writes `logs/test_execution_trace.json`
- writes repair artifacts under `logs/test_repair_traces/` when a code repair is attempted
- updates `run_manifest.json`

If execution fails because of a local environment issue such as missing `pytest`, Chrome startup
problems, or blocked local socket binding, the workflow records the failure and stops without
sending a pointless repair request to Bedrock.

## Test

The deterministic parser, verifier, and retry loop can be tested locally without hitting Bedrock:

```bash
python -m unittest discover -s tests -v
```
