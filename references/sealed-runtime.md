# Parameter sealing, startup unlocking, and device execution

## Flat parameter package

Read original weights and perform text/PLE/vision transformations in a trusted environment, then output only parameters consumed during inference. Target and draft roles may use separate file prefixes and indices, but all files belong in the `models` root. Omit all draft files when there is no draft model. Do not simply concatenate two complete checkpoints or leave links to original weights.

```text
models/
  config.json
  generation_config.json
  model.safetensors.index.json
  target-....safetensors
  private_manifest.json
  draft-config.json                 (only when needed)
  draft.safetensors.index.json      (only when needed)
  draft-....safetensors             (only when needed)
```

Names indicate roles only; preserve framework identifiers required to load the actual model. Use the real loader's consumption inventory to remove training optimizers, statistics/debug tables, duplicated weights, and unused metadata. Do not reuse another model's tensor-name blacklist.

Version the wire protocol, profile, layout, and sealed format independently. Public fields include `profile`, `vocab`, remapped specials, role indices, image specifications, and `complete`; the sealed section uses the format below. Initially write `complete=false`, then atomically mark the package complete after successful validation.

## Sealed format

Use AES-256-GCM with a fresh random `K_data` for every package. The reusable compatible format below has a reference implementation in [sealed_format.py](../scripts/sealed_format.py). Implement complete standards-compliant authentication, not just CTR XOR. [GCM standard](https://csrc.nist.gov/pubs/sp/800/38/d/final)

| Field | Meaning |
| --- | --- |
| `version` | Sealed-format version, matched exactly by the loader |
| `algorithm` | `AES-256-GCM` |
| `package` | Public unique identifier for this package; also the AAD for data-key wrapping |
| `chunk_bytes` | Bytes per chunk, compatible with AES blocks and the random-access row layout |
| `kdf` | `name=scrypt`, `n`, `r`, `p`, and a random 16-byte salt encoded as hex |
| `key_nonce` | Independent random 12-byte nonce used to wrap the data key |
| `wrapped_key` | Hex encoding of the 32-byte encrypted data key followed by a 16-byte tag |
| `tensors` | Records keyed by `role:logical_tensor_name` |
| Tensor record | `ordinal`, original `dtype`, original `shape`, and chunk-ordered 16-byte tags encoded as hex |

Each tensor ordinal is a positive 64-bit integer unique across all roles in the package. Number chunks from zero within a 32-bit range:

```text
nonce = uint64_big_endian(tensor_ordinal) || uint32_big_endian(chunk_index)
AAD   = UTF8(compact_JSON([package, role, tensor_name, dtype, shape, chunk_index]))
```

Specify consistent JSON encoding, including ASCII escaping and absence of extra whitespace. Changing an AAD field must fail authentication. Use a fresh `K_data` when resealing; never encrypt changed plaintext with the same tensor/chunk nonce under the same key.

Safetensors headers may retain logical names, dtypes, shapes, and payload lengths while replacing payloads with equal-length ciphertext and storing tags in the manifest. Loaded values must then be treated only as raw bytes. Ordinary loaders must not numerically convert or quantize them. Integer/floating-point formats are container declarations only. Intercept loading with a custom loader and pass values to their original consumers only after device authentication and decryption.

For random-access row length `row_bytes`, set `alignment=lcm(16,row_bytes)` and round the configured target chunk size down to a multiple of that alignment; the final chunk may be shorter. Derive row length from actual quantized storage rather than a fixed feature width. Partial or variable-length rows require an offset directory and suitable kernel; do not assume uniform rows.

Validate ordinal uniqueness/range, record completeness, dtype/shape/byte counts, tag counts, actual shard offsets, and one-to-one index relationships. Every tensor classified as sensitive must have a record. Missing sealed metadata or records must fail startup rather than enabling a plaintext fallback.

Store plaintext parameter SHA256/comparison reports only in the trusted work directory. Public manifests must not include mappings, plaintext-digest inventories, or source-code paths. AEAD does not hide tensor names/shapes or prevent active loader replacement; trusted distribution of the entire package remains part of the deployment boundary.

## Key wrapping and passwords

Compatible scrypt settings are `N=32768,r=8,p=1,dkLen=32,maxmem=64 MiB`. New deployments may tune these for the actual device and password policy, but must version them and ensure consistent interpretation by endpoints/bootstrap. Changing manifest numbers alone is insufficient.

```text
model_salt = random_16_bytes || ASCII("model-unlock-v1") || zero_byte
K_wrap     = scrypt(password_utf8, model_salt, configured_parameters)
wrapped    = AES256GCM(K_wrap, random_nonce, K_data, UTF8(package))
K_auth     = scrypt(password_utf8, fresh_auth_salt_16_bytes, auth_parameters)
```

`K_data` is a random key, not `K_auth` or the data-transformation seed. Separate salts/domains separate purposes, but the same password still protects both uses; do not claim independent cryptographic factors. Enforce at least 6 characters using consistent Unicode encoding rules. Leading/trailing spaces belong to the password; remove only the terminal line ending.

## Short-lived native bootstrap

1. The Python launcher must not receive the plaintext password. Start a native helper that reads hidden terminal input and restores terminal settings on errors, signals, and exit.
2. Use dedicated locked, nondumpable buffers and check that these protections succeed. Avoid immutable Python strings and implicit logging/debug serialization. Use erasure that the compiler cannot optimize away.
3. Derive authentication material and the unlock key. Authenticate and unwrap `K_data`; exit before engine startup if this fails. Audit the derivation library's temporary allocations too, and terminate the helper when finished to release the whole process.
4. Send only `auth_salt || K_auth` through an inherited anonymous pipe to the gateway. Parameter data keys must not pass through Python, argv, environment variables, configuration, or disk.
5. Establish a restricted local native channel. Send `K_data` only to expected workers created by this launcher, using peer credentials and actual PID/process relationships, and prevent duplicate claims. Matching only the UID does not resist active same-user attacks; restrict recipients precisely even within the trusted-startup boundary.
6. After every expected worker acknowledges device provisioning and CPU-buffer erasure, wipe and exit the helper and remove the channel. Keep no long-lived CPU key broker.
7. Worker failure or replacement requires a full restart and another manual unlock. The launcher must not resend keys from files, environment variables, or regenerated plaintext caches. Multiprocess failures, timeouts, and cancellation must clean up all child processes and channels.

## Device key-provisioning pitfalls

A short host-to-device copy may be inlined by the driver into a CPU command buffer, leaving a copy after the original buffer is erased. An ordinary HtoD copy of a 32-byte key has exposed this residue risk; checking whether a Python variable was deleted is therefore insufficient.

Prefer **device pull** on supported platforms:

1. A native receiver reads the key into a locked/DONTDUMP buffer aligned to the system page size.
2. Register the host page for device access and obtain its device alias.
3. A small kernel reads the mapped host page and writes the key into a device raw-key allocation.
4. Synchronize kernel completion, unregister the mapping, explicitly erase the host page, and send an acknowledgement.
5. Expand the key schedule and initialize authentication state on the device, then erase the raw-key allocation. Retain only the device's expanded key afterward.

This is not proof of zero residue on every backend/driver. Independently scan CPU processes after startup using synthetic random keys, including driver buffers and allocators. If the platform lacks support or the audit fails, do not silently revert to ordinary copying and declare success.

## Parameter loading

- Small sensitive tensors: read only ciphertext on the CPU, upload ciphertext, verify GCM on the GPU, decrypt on the GPU, then deliver final parameters by device-to-device copy. Erase intermediate plaintext device buffers after use.
- Large feature tables: authenticate every complete chunk overlapping the region actually consumed by each rank. Retain only ciphertext in host/pinned memory, or retain ciphertext on the device. Boundary chunks may be verified by multiple ranks.
- Do not expect a standard safetensors reader to decrypt automatically. Do not export sensitive tensors through `.cpu()`, `.numpy()`, or `.item()`. Only scalars such as authentication success/failure may return to the CPU.
- Mapped host ciphertext tables must remain unchanged after startup authentication. The passive-reading boundary allows repeated use after verification; an active writer can create a verification/use race. That requires additional protection and is not covered by this claim.

## Random access to encrypted tables

Authenticate the complete chunk tag first. The device may then use CTR decryption for ciphertext blocks belonging to requested rows. For global byte offset `o`, use the tensor's actual shard mapping to determine:

```text
chunk_index  = o // chunk_bytes
within       = o % chunk_bytes
AES_block    = within // 16
byte_in_block = within % 16
counter      = AES_block + 2
```

With a 96-bit nonce, GCM's tag mask uses the nonce followed by big-endian 1; payload counters start at 2. Prevent block-counter overflow and handle unaligned rows and cross-chunk/shard accesses. Do not confuse global and local row indices.

The kernel decrypts selected rows, dequantizes their actual format, applies the correct scale, and emits device features. Keep PLE hashes, gather indices, plaintext rows, and projections on the device. GPU keys/key schedules, GHASH state, and pointers must not become compilation constants in serialized graphs or kernel caches.

Performance optimizations may use parallel GHASH reduction for authentication, appropriate storage for public device AES tables, chunked uploads, and on-demand gather. Rerun standard vectors and independent-implementation comparisons after every optimization, and check asynchronous streams and graph capture. Never trade away authentication or expose indices to improve throughput.
