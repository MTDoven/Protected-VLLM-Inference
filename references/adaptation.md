# Discover and adapt the ordinary service

## Inventory order

Start with the user-specified entry point, launch scripts, configuration, project dependencies, and model indices. Search bounded file sets, exclude `bkp` and user-prohibited directories, and reject links into them. Do not scan entire ancestor directories looking for historical implementations.

Record the following in the trusted work directory:

1. Actual Python/native runtime, vLLM or llama.cpp revision, and model implementation versions, registration mechanism, entry point, and supported features. Inspect installed code first and use official documentation for version checks; do not assume current online documentation matches the target environment.
2. Every checkpoint tensor's consumers, shape, dtype, sharding, quantization parameters, aliases, vocabulary size/padding, tied-weight status, extra heads, adapters, and draft roles.
3. All token-ID consumers: embeddings, hashes, routing, sampling filters, termination rules, caches, constrained decoding, templates, tool parsers, and reasoning parsers.
4. Image processor behavior: EXIF, color handling, resize/crop, pixel limits, patch/merge/temporal dimensions, normalization, convolution input layout, positional/rotary encodings, windows, interpolation, deeper visual branches, and merger.
5. Service process tree and lifecycle: API, engine, TP/PP/DP workers, helper processes, offload paths, CPU fallbacks, cache directories, crash dumps, and logs.
6. Actual device backend, memory capacities, host-mapping support, compiler compatibility, driver/runtime, and concurrent processes. Reuse the ordinary service's validated configuration and adjust based on measurements.

The read-only inspector collects header information from explicit indices:

```bash
python scripts/inspect_checkpoint.py --root candidate/models \
  --index target=model.safetensors.index.json \
  --index draft=draft.safetensors.index.json
```

This is an inventory aid. It cannot identify every sensitive tensor for an architecture and does not replace loader tracing. Omit the draft index when there is no draft model. Relative subpaths may be inspected for nonflat source layouts; the final candidate must pass `--require-flat`.

## Model adapter contract

Create a neutrally named adapter module in the target project. Concentrate framework dependencies there instead of scattering string-based patches:

| Capability | Required output |
| --- | --- |
| `inspect` | Parameter roles, vocabulary axes, quantization, token consumers, image specification, and parallel layout |
| `transform_text` | Equivalent input/output/draft parameters, remapped special IDs, and lookup state |
| `transform_vision` | Pixel-transformation specification, folded first-layer parameters, and spatial-position rules |
| `sensitive_tensors` | Per-role sealing dependency closure and justification; an empty match must not silently pass |
| `load_sealed` | Role-aware ciphertext loading and device authentication/decryption without a plaintext CPU iterator |
| `build_input` | Engine inputs constructed from protected tokens, image ciphertext and public descriptors; plaintext image intermediates stay on the device |
| `generate` | Autonomous generation and streaming in transformed-ID space |
| `validate` | Architecture-specific equivalence, negative, memory, and performance checks |

For vLLM, use general plugins or model-registration extensions. Ensure activation in every worker and idempotent repeated installation. Do not use an IO plugin limited to another task type for an ordinary generative model. If precise patches to a pinned version are necessary, verify class/function signatures and fail startup on mismatch. [vLLM plugin documentation](https://docs.vllm.ai/en/stable/design/plugin_system/)

For llama.cpp, pin the source revision, preserve a reproducible patch/build recipe and verify source hashes before patching. Trace GGUF loading, the visual projector, GGML tensor placement and sampler backends. Use device-to-device transfers and opaque visual-feature handles at native bindings; returning sampled IDs must not also copy logits, probabilities or features to CPU. Verify synchronization between custom CUDA work and GGML streams, and reject unsupported device sampler fallbacks.

## Text-path features that must not be missed

- For vLLM, use `skip_tokenizer_init` and `detokenize=False`: the engine consumes and returns token IDs. For llama.cpp, remove original tokenizer strings from serving GGUF metadata and use the native token-ID path. In both backends, verify that model code and processors do not instantiate a tokenizer independently. [vLLM engine arguments](https://docs.vllm.ai/en/latest/configuration/engine_args/)
- Handle OpenAI-style messages, templates, image placeholders, tool text, and reasoning markers on the client. Ordinary plaintext chat endpoints must not bypass the protected gateway.
- Equality between token IDs survives permutation. Features involving token strings, ordering, lexical analysis, regex, or JSON grammars need separate adaptation. Silently enabling the original tokenizer is not an adaptation.
- Every speculative-decoding model, shared/nonshared embedding, proposal, accept/reject operation, cache, and stopping rule must use the same ID space. Different draft vocabularies require an explicit bridge. If not adapted, report that the optimization is unavailable.
- Image features enter hidden space directly; changing vocabulary rows alone does not require rotating them. If hidden-channel coordinates are also transformed, prove equivalence across every text/vision bridge and network operator.

## Hardware and runtime adaptation

Do not hardcode device product names, compilation architecture targets, visible devices, CPU affinity, NUMA settings, syscall numbers, or worker counts. Detect the backend and choose supported kernels/operators. Derive compilation targets from the selected devices, and keep secret constants out of caches.

Validate native GPU cryptography, asynchronous streams, pinned/mapped host memory, opaque gather, and graph capture for each backend. CUDA implementations may use the appropriate native APIs; other backends need equivalent modules. A CUDA template is not a cross-backend executable implementation.

Determine key-recipient workers from the actual role distribution rather than assuming a fixed TP count. Multimachine deployment also requires protected key-provisioning channels between machines; a local Unix socket does not provide them.

Set a suitable memory-lock budget for the pinned/mapped buffers actually used. Preserve system and ordinary-service dependencies. Do not remove components merely because they resemble an old toolchain unless dependency, dynamic-linking, and rollback checks show they are unused and cleanup is authorized.

## Determining support

Ordinary text-only autoregressive models generally require vocabulary and token-consumer adaptation. PLE/hash-augmented models additionally require GPU hashing and secure gather. Image models require first-layer linear equivalence and spatial validation as well.

Do not automatically declare audio, video, nonlinear pixel front ends, overlapping convolutions, complex local windows, dynamic vocabularies, or constrained text decoding supported merely because they are multimodal features. Implement and validate what the user needs. If a training-free equivalent construction is unavailable, report the specific obstacle instead of introducing unauthorized training or client-side model inference.
