# Validation, deployment switching, and rollback

## Validation layers

The included CPU synthetic checks validate only reference formats and algebra, not the target model or device implementation. Every new model/machine requires the applicable acceptance work below. Keep results in `WORK_ROOT`; do not retain documentation or test artifacts in the server directory. Classify each check as passed, failed, not run, or not applicable with evidence; requirements listed here are not claims that a deployment has passed them.

Numerical comparisons that inspect plaintext tensors or logits belong only in isolated trusted fixtures. Never enable a diagnostic CPU export in serving code to run them; independently audit the installed production path.

### Formats, passwords, and cryptography

- Test AES-256-GCM against public known-answer vectors and an independent established implementation. Cover empty messages, non-block-aligned lengths, complete chunks, and final partial chunks.
- Tampering with ciphertext, tags, AAD, shapes, roles, ordinals, chunk order, package identity, wrapped keys, or passwords must fail. Test incomplete packages, repeated nonces, missing sensitive records, and out-of-range indices.
- A malformed authenticated image or invalid permutation must reject the request and allow a subsequent valid request. If an encoder exception would kill the whole backend, authenticate/validate on the device before submitting model work and return only status to the gateway.
- Compare GPU results byte for byte with the reference. Test actual streams and graph capture, not just CPU helpers.
- Reject incorrect passwords before engine startup and reject short passwords. Restore terminal echo after success, failure, and cancellation.
- Eliminate old plaintext-parameter bypasses; online loaders must reject unsealed input. Verify complete parameter byte counts, dtypes, and shapes through packaging/unpacking, retaining plaintext checksums only on the trusted audit side.

### Text and PLE

- Compare embeddings and inverse-permuted output logits element by element. Cover special tokens, tied weights, padding, extra heads, and draft models.
- Cover ordinary short text, multiple languages, long context, chunked prefill, decode, different batches, prefix-cache hits/misses, concurrency, and recovery after cancellation.
- Test PLE overflow/negative remainders, EOS reset, request boundaries, padding, each n-gram length, first/last rows across chunks/shards/ranks, and uneven shards.
- Compare gather results for each actual quantization format, scale, zero point, NaN/signed zero, and other relevant boundaries. Disable all online CPU PLE paths and make attempted use fail explicitly.
- Ensure target/draft accept/reject processing never mixes ID spaces. Record distributional equivalence separately from exact token-by-token equality.

### Images and spatial relationships

Generate reproducible synthetic images with asymmetric shapes, different colors, clear text, small text, positional relationships, and single-point differences. Cover one image, identical pairs, different pairs, image swaps, different aspect ratios, and size limits. Identical image pairs alone do not adequately test multi-image behavior.

Compare first-layer/visual outputs numerically between the trusted ordinary model and protected path. Validate positional encoding, windows, merger, and special branches. Report OCR, color, detail, and left/right/up/down results separately. Fix and record normalization, resize/crop, permutation RNG, and quantization tolerances.

For v3, compare independent CPU AEAD/normalization references with the actual GPU implementation, including tags/AAD/nonces, incomplete envelopes, invalid secret permutations and cross-request binding. Test repeated images with new counters, replay across and within connections, concurrent clients and restart nonce/key separation. Add statistical reconstruction and repeated-image linkage attacks against captured serving CPU artifacts; preserving no literal original pixels is not sufficient. Report the public geometry, length, timing and output-ID leakage that remains. Test GPU sampling, including greedy ties and temperature/top-p, without host logits/probability extraction in the serving path.

### Protocol and client

Cover incorrect certificate pins, profile/version mismatches, failed/timed-out authentication, replayed nonces, incorrect blob lengths, out-of-range tokens, oversized geometry, invalid patch orders, overlapping placeholders, cancellation, disconnects, and reconnects. Explicitly reject v2, PNG blobs, clear patch-order fields and compressed wire payloads. Test decoder resource limits locally where the client opens source image files. Confirm that the actual client neither loads GPU software nor invokes a model.

Validate the delivered bundle from the actual `CLIENT_ROOT`, then from a client-only copy without access to `WORK_ROOT` or original checkpoints. Load it through the real CPU client, verify its inventory, file permissions and profile against the accepted server candidate, and compare tokenization, template rendering, token/pixel transformations and response decoding with the validated reference. Cover text/history and each supported image mode. Fix public per-request randomness only in the comparison harness when byte equality is required. Record the delivered paths, artifact hashes and results. Passing against a staging bundle alone, or merely finding JSON files, does not establish a complete client delivery.

Measure timestamps and bytes for every application frame in both directions and calculate peaks over any rolling second. Include large images, concurrency, handshakes, retries, and reconnects. State whether overhead is included and which connections share the quota. If a network-layer cap is required, measure total interface traffic separately.

### Disk and memory boundaries

Keep synthetic inputs, random data keys, unlock keys, and parameter fingerprints in a trusted test controller. Scan the server launcher, API, engine, all workers, and helpers. Exclude the trusted client and provisioning/scanning controllers themselves.

Scan only authorized scopes and do not read user-prohibited directories. Report match types, counts, and necessary locations, without exposing real passwords, keys, mappings, or original-data fragments.

Repeat sampling after key injection, model loading, warmup, sustained text/image/multi-image workloads, and shutdown cleanup. Check:

- Password encodings, raw `K_data`, `K_wrap`, and CPU key-schedule copies. Authentication verifiers and TLS keys have separate scopes; do not conflate this with a claim that no keys exist anywhere.
- Complete/partial original token sequences, original UTF-8 text, original pixels, and fingerprints of hash operands, embedding/output rows, visual first-layer parameters, and feature tables that directly recover mappings.
- EtC RGB/normalized pixels, forward/inverse secret patch order, visual embeddings, image-conditioned logits, and raw/expanded image keys. Include numeric-layout alternatives and known trusted-reference feature fragments; do not restrict the scan to input PNG strings.
- Pinned memory, mapped regions, driver submission buffers, allocators, CPU fallbacks, interprocess shared memory, compilation/graph caches, logs, core dumps, temporary files, and sensitive files represented in page caches.
- Simple attacks such as multiplicative-inverse recovery against a sealed hash table must fail. Failure of one attack does not prove that all reconstruction attacks are infeasible.

Record coverage of relevant CPU-readable regions, unread regions and their reasons, and scan timing. Zero matches provide empirical evidence, not a formal proof. Preserve the exclusions for trusted startup and device inspection in the final report.

## Performance comparisons

Separate the effect of converting the ordinary original model into an equivalent transformed model from the additional cost of parameter sealing/device gather. Compare the full user-facing performance target with the original ordinary service. A second baseline using an unsealed candidate with the same profile may isolate sealing overhead.

Keep devices, parallel configuration, quantization, memory budget, context length, sampling, output length, inputs, client, and rate windows identical. Do not take over occupied devices without authorization. Use warmup and multiple measurement rounds covering at least short text, long text, single images, and multiple images, both serially and at the target concurrency.

For EtC comparisons, fix the secret patch permutation **only in the trusted test harness** and record EtC-plaintext digests there to ensure both candidates receive identical model inputs. V3 ciphertext should differ when keys/nonces differ; ciphertext equality is not the comparison target. Different patch permutations can change floating-point order, output length, and speculative acceptance, confounding the comparison. Do not alter production-client randomness or reuse an AEAD nonce to fix this. Retain initial measurements and the evidence for methodology corrections.

If a fixture suppresses EOS to measure a fixed output length, apply it equally to both candidates, disclose it, and verify ordinary stopping separately. Distinguish native-engine throughput from end-to-end TLS/client/traffic-limited throughput. Exact tokens on fixed samples establish regression equivalence for those samples, not general visual quality; report synthetic and natural-image coverage separately.

Report definitions and percentiles for throughput, TTFT, and TPOT, output token counts, speculative acceptance, CPU/GPU utilization, host pinned memory, startup time, and network bytes. State whether authentication/setup time is included. Do not report only the best round.

```text
throughput_loss = 1 - protected_throughput / baseline_throughput
latency_growth  = protected_latency / baseline_latency - 1
```

Apply the user's budget per scenario. The default target of at most 10% for each metric is not an inherited performance guarantee. Diagnose overruns; do not meet the target by reducing authentication, disabling essential features, or lowering precision without disclosure.

## Deployment transaction

1. Build the candidate in `WORK_ROOT`, fully verify parameters, and run real functional tests. Prepare the matching client bundle independently of the production unlock password. Record source versions and candidate-file hashes.
2. Acquire a deployment lock for the actual `SERVER_ROOT`. Check for user modifications, running services, and available storage. Perform already authorized shutdowns/switches directly. If downtime is not authorized, prepare a complete reviewable result before asking for a specific window.
3. Back up old parameters, code, configuration, launchers, and required runtime components in the trusted work directory. Preserve TLS and existing client-bundle compatibility. Backup placement must satisfy the threat model; renaming a directory is insufficient.
4. Use atomic rename within a filesystem. Across filesystems, copy and verify first. Install or verify the complete matching bundle in the actual `CLIENT_ROOT`; preserve existing client assets until the authorized switch. For a new deployment, deliver password-independent client assets even if server sealing must wait for manual input. Record each step and support restoring all old contents if any step fails. Do not roll back only models while leaving the new loader installed.
5. Update the actual server's model root, plugins, launcher, dependency entry points, and configuration. Verify that provisioning preserves the already delivered client seed/profile. Start from the real entry point, unlock manually, and run text/image, authentication, and cancellation smoke tests using the delivered client directory. Confirm the service actually loads the new package.
6. Leave the service running or stop test services as requested, recording port/process state. Do not silently leave multiple test services running or alter unrelated processes.

For rollback, stop the relevant service, restore matching models/code/config/runtime, verify the original profile/client compatibility, and restart with manual unlocking. Test a complete rollback in an isolated copy and retain transaction records on failure. Do not delete backups without authorization.

## Migration and completion criteria

To migrate a client, copy code, lock files, the protected bundle, and connection templates; rebuild `.venv` instead of copying the old virtual environment. For the server, rebuild native modules for the target machine, update dynamic dependencies and device settings, and preserve the parameter format. Compiled artifacts are not universally portable between machines.

Final acceptance evidence must include supported adaptations and limitations, whether the profile changed, whether the data key was rewrapped, the sensitive-tensor set and byte count, indices/file layout, functional/cryptographic/disk/memory/bandwidth/performance results, actual deployment-switch status, backup/recovery procedures, test-service state, and the effective protection boundary. Do not present historical machine details, fixed model sizes, or old passing figures as new deployment results.

Record client-bundle installation, server-parameter installation and running-service status independently. If manual production-password entry remains pending, identify that specific remaining step while still delivering the validated client assets. Do not mark the client complete while its bundle exists only in staging or depends on a future server-provisioning command.

For a documentation-only remote-client handoff, validate the protocol with a trusted reference client and report remote-client installation/acceptance as outstanding. Honor a requested stopped final state: verify service/test-process exit, listener closure and release of the assigned GPU allocations without stopping unrelated workloads.
