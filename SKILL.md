---
name: protect-vllm-inference
description: Build a protected inference service and CPU client on an existing vLLM or llama.cpp server without training, using equivalent token transformations, EtC image transformations, client-to-device authenticated image encryption, sensitive-parameter encryption, and device-only image processing. Use when the user supplies a model, machine, server directory, and client directory and wants to protect uploaded data while retaining autonomous server generation.
---

# Protect an existing vLLM or llama.cpp inference pipeline

Deliver a runnable, reproducible server and CPU client with validated functionality and protection boundaries. Adapt the existing ordinary service without training, client-side model execution, or per-token client computation. This skill provides an implementation workflow and reusable references, not a drop-in plugin for every model.

## Inputs and scope

Start with the supplied model, target machine, `SERVER_ROOT`, and `CLIENT_ROOT`. The model may be a checkpoint or a model identifier; first locate the parameters and implementation actually used by the ordinary service. Discover paths or obtain them from the current task. Examples use relative paths only.

Record these parameters:

| Parameter | Handling |
| --- | --- |
| `MODEL_SOURCE` | Complete weights and required configuration loaded by the ordinary service; tokenizer resources stay on the trusted side |
| `MACHINE` | Discover the execution connection, operating system, device backend, device count, device/host memory, compiler, and driver on the target machine |
| `SERVER_ROOT` / `CLIENT_ROOT` | User-specified directories; preserve existing application and startup semantics |
| `WORK_ROOT` | Trusted provisioning, documentation, testing, and backup directory outside the service directory; if unspecified, choose a nonconflicting location in the current working directory |
| `EXCLUDED_DIRS` | Exclude every directory named `bkp` by default and add all user-prohibited paths; do not read, traverse, or follow links into them |
| `THREAT_SCOPE` | Distinguish passive disk/CPU-memory inspection after trusted startup from GPU, driver, startup-time, and active attacks |
| `TRAFFIC_BUDGET` | Default combined upload/download limit: 10,000,000 B/s; specify application versus interface bytes and single-session versus aggregate connections |
| `PERFORMANCE_BUDGET` | Follow the user's target; otherwise use at most 10% throughput loss and 10% latency increase as targets requiring measurement |

Preserve choices already established in the conversation. Ask only for missing information that affects feasibility, authority, or security claims and cannot be discovered from the code; continue independent work meanwhile. Do not request authorization again for already authorized implementation steps.

## Required invariants

- Both server and client require manual password entry at startup, with at least 6 characters. Never place the password in command-line arguments, environment variables, logs, or new plaintext files. By default, derive separate authentication and parameter-unlock keys from one server startup password; keep both separate from the data-transformation seed. Honor an explicit existing requirement for separate passwords.
- The client performs only CPU tokenization, templating, permutation, image processing, authenticated image encryption, authentication, and response decoding. V3 image payloads are uncompressed. Do not install inference frameworks or perform neural-network computation on it.
- For image confidentiality against CPU inspection, encrypt EtC pixels and their secret patch order together on the client, authenticate/decrypt only on the device, and retain visual features and image-conditioned numerical outputs on the device through sampling. CPU processes may handle ciphertext, public geometry, and transformed output IDs. EtC scrambling and sealed model parameters alone do not prevent statistical image reconstruction.
- Deliver the complete matching client bundle in the actual `CLIENT_ROOT`, not only in `WORK_ROOT` or behind a future provisioning command. Tokenizer, template, processor configuration, and transformation-seed delivery do not require the server unlock password; complete them even when manual server sealing/startup remains pending.
- The server accepts transformed tokens and authenticated ciphertext containing EtC images and secret patch order, independently performs prefill, decode, sampling, and supported speculative decoding, and returns transformed tokens. Do not request client intermediate results at every generation step.
- Do not store the original tokenizer, client seed, complete bidirectional token mapping, plaintext mapping-equivalent parameters, or original images on the server. Passwords, parameter data keys, image keys, and unlock keys must not remain in CPU-readable buffers after trusted startup.
- Mark a feature supported only after implementing a training-free equivalent adaptation. Unsupported branches must fail explicitly, without silently reverting to original text/images, CPU decryption, or an unprotected ordinary endpoint.
- Do not modify `bkp`, user-excluded directories, or conda environments. Install dependencies in each project's `.venv`. Discover and use a compatible system device toolchain; do not hardcode toolchain locations, device models, compute capabilities, device indices, NUMA nodes, or thread counts.
- Use English for server-owned code, comments, prompts, logs, and saved information. Use neutral application names, while retaining framework classes, architecture identifiers, and licenses required for loading. Renaming is not a security mechanism.
- Keep the server parameter directory flat and include only inference-required parameters and configuration, with no subdirectories or symlinks to original weights. Keep original checkpoints, conversion intermediates, documentation, tests, and historical parameters in trusted `WORK_ROOT`; include reproduction instructions in the client directory.
- Preserve existing token permutations, image seeds, and profiles during migration unless the user requests rotation. Rewrapping parameter keys is not data-transformation rotation.
- Version image transport independently of model/profile formats. Reject unsupported or unencrypted image formats; never silently fall back to CPU image decryption or a legacy clear-image path. Coordinate breaking protocol upgrades with the remote client and deliver a self-contained agent handoff when its source is on another machine.

## Implementation workflow

1. **Establish the boundary and inventory the ordinary service.** Read [Architecture and trust boundaries](references/architecture.md) and [Discovery and adaptation](references/adaptation.md). Obtain the ordinary-service baseline, parameter-consumer relationships, and available resources. Historical performance on the machine where this skill was created is not evidence for a new machine.
2. **Adapt the complete data path.** Always read [Text and PLE](references/text-path.md); for images, also read [EtC and the visual path](references/image-path.md). Audit tokenizers, special tokens, sampling, draft models, caches, and every token-derived index. Changing input embeddings alone is insufficient.
3. **Transform and seal in a trusted provisioning environment.** Follow [Parameter format and device runtime](references/sealed-runtime.md) for flattening, sensitive-tensor classification, AEAD encryption, native bootstrap, device-side authentication/decryption, and encrypted-table gather where needed. Produce a verifiable candidate before replacing serving parameters.
4. **Implement the gateway and CPU client.** Follow [Protocol and client](references/protocol-client.md) for matching protocol versions, certificate verification, password authentication, rate limits, cancellation, local decoding, and complete bundle delivery. Install the accepted client assets and validate loading from the actual client directory; do not reuse machine-specific addresses, certificate fingerprints, test images, or password files.
5. **Validate, then switch deployment.** Follow [Validation and deployment](references/validation-deployment.md) for functional equivalence, rejection tests, disk/memory scans, bandwidth checks, and matched-input performance measurements. Back up old contents, update the actual `SERVER_ROOT`, and verify the real launch path and complete rollback. Passing in staging is not deployment completion.

If the scope includes GPU, register, or driver inspection, first verify the available hardware root of trust, trusted execution, and remote attestation. If these cannot satisfy the requirement, explicitly propose the narrower disk/CPU boundary and use it only if already authorized or subsequently accepted. Do not label a downgrade as satisfying the original requirement. AES parameter sealing or variable obfuscation does not solve live GPU white-box attacks.

## Included references and helpers

- [scripts/inspect_checkpoint.py](scripts/inspect_checkpoint.py): reads only safetensors headers and explicit indices, checks file relationships, and lists sensitive-parameter candidates requiring dependency tracing. It neither reads tensor values nor determines security automatically.
- [scripts/sealed_format.py](scripts/sealed_format.py): nonce, AAD, password derivation, and AEAD format reference for trusted offline provisioning. **Never import it into an online server decryption path.**
- [assets/wire.py](assets/wire.py): CPU protocol, authentication, and rate-limiting core that can be copied to both endpoints. TLS, request-semantic validation, identity quotas, and vLLM adaptation still need implementation.
- [assets/image_transport.py](assets/image_transport.py): v3 public image-envelope, geometry, nonce and AAD contract; no image decryption implementation. [Synthetic interoperability vector](assets/image_v3_test_vector.json) checks client and device implementations without production credentials.
- [scripts/check_reference.py](scripts/check_reference.py): synthetic checks for formats, token/PLE/vision algebra, and protocol rate limits. These do not prove successful adaptation of the target model or device.

Example commands; select the interpreter and directories for the current task:

```bash
python scripts/inspect_checkpoint.py --root candidate/models --index target=model.safetensors.index.json
python scripts/check_reference.py
```

The second command requires `numpy` and `cryptography` in the test environment. Do not modify global or conda environments to run it. See [sources.md](references/sources.md) for background references.

## Final delivery

Report the server/client actually modified, launch commands, password purposes, migration instructions, backup/rollback locations, passed tests, and uncovered boundaries. Save acceptance evidence for the current machine rather than copying historical results. Explicitly identify any unadapted branches, incomplete memory audits, or exceeded budgets. Generating this documentation or an encrypted file is not end-to-end delivery.

Report client-bundle installation, server-parameter installation, and service startup separately. Pending manual password entry must not conceal missing password-independent client assets. Include the delivered bundle path and its validation evidence.

When the user explicitly limits a remote-client change to documentation, preserve its existing bundle and deliver the migration guide instead of claiming client installation or end-to-end acceptance. Record remote-client implementation and validation as outstanding.
