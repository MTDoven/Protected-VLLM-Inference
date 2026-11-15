# Protected-VLLM-Inference

## Purpose and use cases

Protect text and images uploaded to an existing vLLM server, without retraining the model or running model inference on the client.

Use this skill when you already have a working vLLM deployment and want a matching CPU-only client, protected input processing, and encrypted sensitive parameters. The server continues generating independently, without per-token client round trips.

This is a Codex skill with reference code. Codex adapts and validates the implementation for your model and machine.

## Quick start

Clone this repository into your working directory:

```bash
git clone "https://github.com/MTDoven/Protected-VLLM-Inference.git"
```

Open Codex in that working directory and send the following request, replacing the example values:

```text
Read Protected-VLLM-Inference/SKILL.md and implement the protected setup.

Model: ./checkpoints/source
Machine: the current machine
Existing server: ./server
Server launch command: ./server/start.sh
Client destination: ./client
Trusted work directory: ./private-work

Validate the result, back up the existing deployment, and provide
startup, client reproduction, and rollback instructions.
```

Give Codex access to the target machine and state whether the service is running. For a remote machine, configure the connection first. Do not put passwords or private seeds in the prompt.

## What you get

- A server using COVERT-style text transformations, EtC image processing, and device-side decryption of sensitive parameters.
- A CPU-only client with TLS, manual startup passwords, and a default combined application traffic limit of 10 MB/s per client instance.
- A validated deployment, client setup instructions, backups, and a rollback procedure.

Model-specific features and performance must be verified during adaptation. Existing `bkp` directories and conda environments are excluded; dependencies stay in project-local `.venv` directories.

## Protection scope

Token permutation and EtC are not general-purpose cryptographic encryption. See the [security boundary](references/architecture.md) before choosing this approach.

## Details

- [Skill instructions](SKILL.md): full implementation workflow.
- [Validation and deployment](references/validation-deployment.md): acceptance tests and rollback.
- [Reference checks](scripts/check_reference.py): synthetic CPU tests; requires NumPy and cryptography.
