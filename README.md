# proofica

Minimal Python starter for a LangGraph agent that calls Amazon Bedrock through the AWS `Converse` API, using Meta Llama 4 Maverick as the default model target.

## What this starter includes

- `src/bedrock_langgraph_agent/`: the LangGraph code
- `.env.example`: local environment variables for AWS/profile selection
- `config/agent.example.yaml`: non-secret runtime settings kept outside the code

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
