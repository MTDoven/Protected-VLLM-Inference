# Transport, authentication, rate limits, and client delivery

## Startup and certificates

The server's native bootstrap reads a password of at least 6 characters once by manual entry; the gateway receives only derived authentication material. The client reads a hidden password manually and applies the same length/encoding constraints. The password is not the data-transformation seed, and changing it alone does not rotate token permutations. Changing the server unlock password requires rewrapping the data key in a trusted environment and aligning authentication behavior.

Use a binary TLS WebSocket channel. Prefer standard CA/hostname verification, or use a certificate DER SHA256 pin distributed through a trusted channel. In pin mode, perform a constant-time comparison before sending any authentication proof or application data. Disabling CA verification alone is not TLS identity authentication. Distribute certificate updates through a trusted channel and reject an incorrect pin immediately.

For a new deployment, configure its own URL, port, certificate and pin; do not copy unrelated machine identities. During an in-place protocol upgrade, preserve the existing endpoint and TLS identity unless rotation is requested. Store TLS private keys in restricted server files. Set self-signed certificate validity and rotation according to deployment configuration. Expose only protected application entry points; do not use the existing plaintext API as a fallback.

## Wire version 3 and device-only image envelopes

`assets/wire.py` provides the format core. Copy the same version to both endpoints or generate both from one shared build source to prevent drift.

Handshake:

```text
server -> challenge {type, version:3, profile, salt, nonce, image_transport}
client -> auth      {type, version:3, profile, proof}
server -> authenticated {type, version}
```

`salt` is 16 random bytes generated at server startup; `nonce` is 32 random bytes per connection, both encoded as hex. `profile` is the matching 64-character ASCII profile identifier. Both endpoints derive `K_auth = scrypt(UTF8(password), salt, N=32768,r=8,p=1,dkLen=32,maxmem=64MiB)`. The proof is encoded as hex:

```text
HMAC_SHA256(K_auth, ASCII("private-v3") || zero_byte || nonce || ASCII(profile)
            || SHA256(canonical(image_transport)))
```

Use each nonce once. Validate types, lengths, profile, and protocol version, and close on authentication timeout. Do not log proofs, passwords, or complete inputs. This mechanism depends on verified TLS; it is not a PAKE and does not resist impersonation after verifier disclosure or offline guessing of weak passwords.

`image_transport` advertises AES-256-GCM, `etc-rgb-u8-q-le32-v1`, a fresh startup image salt, an eight-byte connection nonce prefix, the public layout/patch size and scrypt parameters. Derive `K_image = scrypt(UTF8(password), b"private-image-v3\0" || image_salt || ASCII(profile), N=32768,r=8,p=1,dkLen=32,maxmem=64MiB)`. Here `\0` denotes one zero byte. Only the short-lived native bootstrap and trusted client derive this key on CPU; serving workers retain it only on the GPU. It is independent of `K_auth`, `K_data` and the transformation seed, while still relying on the same password's strength.

Its exact fields are `format`, `cipher`, `salt` (16-byte hex), `nonce_prefix` (8-byte hex), `layout`, `patch_size`, and `kdf={name:"scrypt",n:32768,r:8,p:1,length:32}`. Validate these before running the KDF, including agreement with the local bundle; reject unsupported values instead of accepting server-selected resource costs. Require version 3 in both `challenge` and `authenticated`. Keep image keys in client memory only and discard them on shutdown or rederive them after a server restart.

For each tile, encrypt HWC RGB uint8 EtC bytes followed by little-endian uint32 `q`. The nonce is `connection_prefix[8] || tile_counter_be32`; counters start at one and increase across requests on that connection. Each startup uses a fresh key, connection prefixes are unique for that key, and exhausted counters require reconnecting. Never independently restart a gateway with the old worker keys and a reset prefix counter.

AAD is `b"private-image-v3\0" || challenge_nonce[32] || ASCII(profile) || image_index_le32 || tile_index_le32 || SHA256(token_blob) || SHA256(canonical(image_descriptor))`. Indices start at zero; the descriptor includes the complete image tile list. Canonical JSON sorts keys, uses ASCII escapes and compact separators, and rejects nonfinite values. [The public contract](../assets/image_transport.py) and [synthetic interoperability vector](../assets/image_v3_test_vector.json) are normative for this format. No v2 or clear-image fallback is provided.

## Message encoding

A logical message consists of:

```text
uint32_little_endian(header_byte_length)
UTF8(compact_JSON(metadata with blob_lengths))
blob_0 || blob_1 || ...
```

Defaults are a 128 MiB maximum logical message and a 1 MiB JSON header. Each chunk contains at most 60,000 data bytes, preceded in its WebSocket binary frame by a one-byte final-chunk flag, `0` or `1`. The maximum frame is 60,001 bytes. Smaller task-specific budgets or versioned changes are allowed, but both endpoints must agree.

Reject nonbinary frames, invalid final flags, noninteger or negative byte counts, inconsistent total lengths, oversized headers, duplicate JSON keys, and nonfinite numbers. Disable WebSocket compression, limit max_queue, and separately bound decoding, request construction, image dimensions, and memory use.

Generate metadata and blob layout:

- Metadata includes `type=generate`, `version`, `profile`, `sampling`, and `stop_token_ids`.
- Each entry in `images` contains `offset`, `length`, `grid` and `tiles`, ordered by placeholder appearance. Each tile has `width`, `height`, `suffix` and `tokens`. Geometry remains model-specific and public.
- The first blob contains transformed token IDs as little-endian uint32 values.
- Each tile contributes one envelope blob: 12-byte nonce followed by ciphertext and the 16-byte GCM tag. Raw RGB and secret order are inside it; the plaintext size is exactly `3*width*height + 4*patch_count`.
- Responses use `tokens` with a transformed-ID blob and `done` with a finish reason. Errors expose only stable error codes, not full exceptions or input values.
- `cancel` carries version 3 and profile, no blobs, and interrupts the active request; send `cancelled` after engine abort completes. Disconnects also abort. By default, allow one active request per connection and return `Busy` for a second request. Consume counters for received envelopes even when requests are busy; cancelled/failed sends require reconnecting so the endpoints cannot disagree about counters.

The supplied geometry validator supports `minicpm` (patch 14, merge 2, `grid=[gx,gy]`, one overview plus up to nine slices) and `qwen` (patch 16, merge 2, `grid=[1,Hpatch,Wpatch]`, one tile). Qwen temporal duplication occurs only on the device. Exact suffix/token-count rules and size limits are in `assets/image_transport.py`; these are implemented layouts, not defaults for every model. A new geometry requires a coordinated, validated contract change.

The gateway assigns random neutral request IDs; clients must not add unsupported request fields. Context limits include expanded image tokens and output tokens. The supplied validator defaults to 32,768 total tokens, permits 1–32,767 output tokens, temperature 0–2 and top_p 0.0001–1, and accepts at most 64 stop IDs within the vocabulary. A backend may supply a different context limit; align the client with its actual configuration. Do not pass unknown user metadata directly into the engine.

## Defining the 10 MB/s limit correctly

By default, application upload and download each stay within 5,000,000 B/s, for a combined maximum of 10,000,000 bytes in any rolling second, including the one-byte chunk framing. Use a rolling window without an initial token-bucket burst. Loops, retries, reconnects, and concurrent connections from the same client must share the budget rather than resetting it per request.

Share the server's outbound limiter across the service or authenticated principal as required by the user. Creating only per-connection limiters does not establish a global cap. Single-session compatibility and service-wide quotas are different promises. This skill defaults to aggregation across all connections of one deployed client instance. If the user requires a cap across all clients, configure and test a server-wide quota.

Delaying parsing after reception cannot retract bytes already received by the network interface. The official client's send limiter controls upload; the server's send limiter controls download. For an uncooperative client, receive limiting mainly supplies backpressure and does not prove a hard link-rate cap.

The application-byte budget excludes TLS/WebSocket/TCP/IP framing, retransmissions, and handshakes. If the user requires a physical-link total, measure actual transmitted bytes and apply the target system's network shaping, accounting for overhead and multiple connections. Do not equate a 10 MB/s application limit with a network limit.

## CPU client

Minimum capabilities include tokenizers, restricted template execution, array permutations, Pillow or an equivalent image library, a standard AES-GCM implementation, scrypt, and TLS/WebSocket. Generate a reproducible lock file for the actual implementation and install into the client's `.venv`. Do not install vLLM, GPU torch, device runtimes, or vision models. Hiding devices is only an auxiliary measure; dependencies and runtime calls must establish that no GPU computation occurs.

The client bundle contains public tokenizer/config/template/processor specifications plus a private seed file with mode 0600 and restricted parent-directory permissions. Reject symlinked secret files and overly broad permissions. Transfer seeds through a trusted channel only to trusted clients; do not include them in server images, Git, or public test packages.

Install these assets in `CLIENT_ROOT/bundle/`, or the documented directory actually loaded by the client, before handoff. A bundle retained only in `WORK_ROOT`, a staging candidate, or a script that will generate it later is not client delivery. The inventory must cover the following resources; filenames may differ when the runtime uses a documented equivalent:

| Resource | Typical files |
| --- | --- |
| Complete tokenizer vocabulary, merges and tokenization rules | `tokenizer.json`, or equivalent model-specific tokenizer resources |
| Special-token settings and exact chat template | `tokenizer_config.json`, `chat_template.jinja` |
| Image preprocessing specifications for supported image input | `preprocessor_config.json` |
| Private transformation seed and matching profile metadata | `private.json` or a private seed file, plus profile configuration |

Derive or export these files from the actual model resources and accepted transformation seed. Do not copy another model's tables or add unused JSON files just to match its directory listing. Verify that the real client loads the delivered representation and that any duplicate representations agree.

Bundle generation and installation are independent of the server unlock password. If manual password entry is still needed to seal server parameters, deliver and validate the client assets first and report only the remaining server steps as pending. Later provisioning must reuse the delivered seed/profile, verify compatibility, and preserve the bundle; reject a conflicting existing bundle instead of silently overwriting or rotating it. Installation failure and rollback must restore any previously delivered client assets.

For output handling, validate transformed-ID ranges, apply the inverse permutation, and append original tokens while preserving required special markers. Incremental decoding must handle UTF-8 across token boundaries and tokenizer cleanup rules, flush at the end, and avoid dropped characters or erroneous fallback output. If repeatedly decoding all tokens and printing the new suffix cannot guarantee prefix stability, implement the tokenizer's appropriate streaming strategy.

An optional continuous `example.sh` may alternate text, single-image, and two-image requests over one connection. Implement correct cancellation, finite-run exit status, reconnect backoff, request/first-token timing, and success/failure counts. Use locally generated synthetic images instead of machine-specific images/dependencies. Do not save input/output logs by default or search for a particular password file. Only when explicitly requested with a supplied source may the test controller read an existing password file; never create a new plaintext copy.

## Required client reproduction documentation

Document supported OS/Python versions, creating `.venv` in a clean environment, dependency locking, the copy list and exclusions for `.venv`/caches, trusted bundle transfer, URL and certificate-pin configuration, manual password entry, text/image/multi-image/history usage, loop tests, cancellation and errors, traffic accounting, and protection boundaries.

Ordinary client deployment does not require the original model checkpoint or offline provisioning-tool dependencies. If provisioning tools are retained, label them separately as trusted offline provisioning so users do not infer that every client needs model weights.

When the client is on another machine and only a handoff is requested, provide a self-contained `client_edit.md`: preserve the existing bundle/seed/profile and preprocessing, specify handshake/KDF/proof, encrypted payload/AAD/nonce lifecycle, request/cancel fields, limits and rejection behavior, and include the public synthetic vector plus tests for both intended backends. Do not claim that writing this guide installs or validates the remote client. V3 servers require that client upgrade before image or text requests can connect.
