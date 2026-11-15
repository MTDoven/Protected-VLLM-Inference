# Transport, authentication, rate limits, and client delivery

## Startup and certificates

The server's native bootstrap reads a password of at least 6 characters once by manual entry; the gateway receives only derived authentication material. The client reads a hidden password manually and applies the same length/encoding constraints. The password is not the data-transformation seed, and changing it alone does not rotate token permutations. Changing the server unlock password requires rewrapping the data key in a trusted environment and aligning authentication behavior.

Use a binary TLS WebSocket channel. Prefer standard CA/hostname verification, or use a certificate DER SHA256 pin distributed through a trusted channel. In pin mode, perform a constant-time comparison before sending any authentication proof or application data. Disabling CA verification alone is not TLS identity authentication. Distribute certificate updates through a trusted channel and reject an incorrect pin immediately.

Do not carry over a particular machine's URL, port, certificate private key, or pin. Store TLS private keys in restricted server files. Set self-signed certificate validity and rotation according to deployment configuration. Expose only protected application entry points; do not use the existing plaintext API as a fallback.

## Compatible wire version 2

`assets/wire.py` provides the format core. Copy the same version to both endpoints or generate both from one shared build source to prevent drift.

Handshake:

```text
server -> challenge {type, version, profile, salt, nonce}
client -> auth      {type, profile, proof}
server -> authenticated {type, version}
```

`salt` is 16 random bytes generated at server startup; `nonce` is 32 random bytes per connection. Both endpoints derive `K_auth`. The proof is:

```text
HMAC_SHA256(K_auth, ASCII("private-v2") || zero_byte || nonce || UTF8(profile))
```

Use each nonce once. Validate types, lengths, profile, and protocol version, and close on authentication timeout. Do not log proofs, passwords, or complete inputs. This mechanism depends on verified TLS; it is not a PAKE and does not resist impersonation after verifier disclosure or offline guessing of weak passwords.

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
- Each entry in `images` contains the actual grid and prompt offset, ordered by placeholder appearance.
- The first blob contains transformed token IDs as little-endian uint32 values.
- Each image contributes two further blobs in order: EtC PNG and public patch permutation as little-endian uint32 values.
- Responses use `tokens` with a transformed-ID blob and `done` with a finish reason. Errors expose only stable error codes, not full exceptions or input values.
- `cancel` interrupts the active request; send `cancelled` after engine abort completes. Disconnects also abort. By default, allow one active request per connection and return `Busy` for a second request.

Use random neutral request IDs, not IDs derived from original inputs. Context limits include expanded image tokens and output tokens. Sampling values must be finite and within supported ranges; stop IDs must fit the vocabulary. Do not pass unknown user metadata directly into the engine.

## Defining the 10 MB/s limit correctly

By default, application upload and download each stay within 5,000,000 B/s, for a combined maximum of 10,000,000 bytes in any rolling second, including the one-byte chunk framing. Use a rolling window without an initial token-bucket burst. Loops, retries, reconnects, and concurrent connections from the same client must share the budget rather than resetting it per request.

Share the server's outbound limiter across the service or authenticated principal as required by the user. Creating only per-connection limiters does not establish a global cap. Single-session compatibility and service-wide quotas are different promises. This skill defaults to aggregation across all connections of one deployed client instance. If the user requires a cap across all clients, configure and test a server-wide quota.

Delaying parsing after reception cannot retract bytes already received by the network interface. The official client's send limiter controls upload; the server's send limiter controls download. For an uncooperative client, receive limiting mainly supplies backpressure and does not prove a hard link-rate cap.

The application-byte budget excludes TLS/WebSocket/TCP/IP framing, retransmissions, and handshakes. If the user requires a physical-link total, measure actual transmitted bytes and apply the target system's network shaping, accounting for overhead and multiple connections. Do not equate a 10 MB/s application limit with a network limit.

## CPU client

Minimum capabilities include tokenizers, restricted template execution, array permutations, Pillow or an equivalent image library, and TLS/WebSocket. Generate a reproducible lock file for the actual implementation and install into the client's `.venv`. Do not install vLLM, GPU torch, device runtimes, or vision models. Hiding devices is only an auxiliary measure; dependencies and runtime calls must establish that no GPU computation occurs.

The client bundle contains public tokenizer/config/template/processor specifications plus a private seed file with mode 0600 and restricted parent-directory permissions. Reject symlinked secret files and overly broad permissions. Transfer seeds through a trusted channel only to trusted clients; do not include them in server images, Git, or public test packages.

For output handling, validate transformed-ID ranges, apply the inverse permutation, and append original tokens while preserving required special markers. Incremental decoding must handle UTF-8 across token boundaries and tokenizer cleanup rules, flush at the end, and avoid dropped characters or erroneous fallback output. If repeatedly decoding all tokens and printing the new suffix cannot guarantee prefix stability, implement the tokenizer's appropriate streaming strategy.

An optional continuous `example.sh` may alternate text, single-image, and two-image requests over one connection. Implement correct cancellation, finite-run exit status, reconnect backoff, request/first-token timing, and success/failure counts. Use locally generated synthetic images instead of machine-specific images/dependencies. Do not save input/output logs by default or search for a particular password file. Only when explicitly requested with a supplied source may the test controller read an existing password file; never create a new plaintext copy.

## Required client reproduction documentation

Document supported OS/Python versions, creating `.venv` in a clean environment, dependency locking, the copy list and exclusions for `.venv`/caches, trusted bundle transfer, URL and certificate-pin configuration, manual password entry, text/image/multi-image/history usage, loop tests, cancellation and errors, traffic accounting, and protection boundaries.

Ordinary client deployment does not require the original model checkpoint or offline provisioning-tool dependencies. If provisioning tools are retained, label them separately as trusted offline provisioning so users do not infer that every client needs model weights.
