# proofica

Minimal Python starter for a LangGraph agent that calls Amazon Bedrock through the AWS `Converse` API, using Meta Llama 4 Maverick as the default model target.

## What this starter includes

- `src/bedrock_langgraph_agent/`: the LangGraph code
- `.env.example`: local environment variables for AWS/profile selection
- `config/agent.example.yaml`: non-secret runtime settings kept outside the code
- `examples/checkout_form.html`: draft HTML page used by the page-object workflow

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

## Test

The deterministic parser, verifier, and retry loop can be tested locally without hitting Bedrock:

```bash
python -m unittest discover -s tests -v
```
