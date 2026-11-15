# Text reparameterization and token-derived computation

## Vocabulary permutation

Let `V` be the logical vocabulary size, `t` an original token, `pi` the client's fixed permutation, and `u = pi(t)` the transmitted ID. Generate the permutation during trusted provisioning. The client retains the seed and can compute the inverse; the server must not store a separate complete `pi` or `inv_pi`.

For input embedding `E`, output projection `L`, and output bias `b`:

```text
E_private[pi(t), :] = E[t, :]
L_private[pi(t), :] = L[t, :]
b_private[pi(t)]    = b[t]
```

For transposed storage, sharding, and tied weights, transform the actual vocabulary axis and preserve sharing. Do not treat padding rows as sampleable vocabulary; retain the original valid-vocabulary mask. Apply the same transformation to every draft model and other vocabulary output head.

Hidden computation retains its original semantics; the output distribution satisfies `p_private[pi(t)] = p_original[t]`. The client applies the inverse permutation before decoding. Equal sampling distributions do not guarantee identical tokens from the same RNG stream: ordering, tie breaking, and top-k/top-p boundaries require separate comparison. Deterministic samples without ties allow exact comparison of original token sequences.

## Seeds and versions

For an existing bundle, preserve its PRNG, domains, vocabulary size, and algorithm version. Keeping the seed while changing the RNG is not compatible. One existing compatible algorithm computes SHA256 over `seed_bytes || domain_utf8`, interprets it as a little-endian integer to initialize NumPy `default_rng`, and generates a permutation. Domains include `tokens-v1`, `pixels-v1`, `ple-{head}`, and `ple-sign-{head}`. Pin dependency versions and the algorithm, and retain synthetic test vectors.

This PRNG is not the source of a cryptographic security guarantee. New profiles may use a defined cryptographic pseudorandom stream and unbiased Fisher-Yates shuffle, but must reconvert the matching model and explicitly update the algorithm version. Do not mix algorithms or silently apply a PRNG upgrade to an existing profile.

A public `profile` may be derived from compatibility metadata and a one-way seed digest; it must not contain the seed. Restrict access to the private client bundle and include only necessary public information in the deployment manifest.

## Special tokens and engine behavior

Individually remap BOS/EOS/PAD, multiple termination markers, image/video boundary and placeholder tokens, forced tokens, bad-word tokens, logit biases, stop sequences, and other semantic token fields in model configuration. Do not blindly permute every integer.

Render templates on the client, then tokenize and transform. Visual placeholder length depends on the token count after image preprocessing. When expanding one placeholder, update offsets and image ordering together. The server validates token ranges, placeholder intervals, termination-ID ranges, and request length without accessing vocabulary text.

Use numeric stop IDs on the server, not stop strings requiring plaintext decoding. Restore and parse tool-call/reasoning output markers on the client. If server-side parsing is required, design a protected parser separately. Isolate prefix caches by profile and session/tenant salt to prevent cross-user cache probing; invalidate old caches after mapping rotation.

## The PLE / n-gram hashing obstacle

Some models hash the original numeric token IDs and look up a large feature table. Reordering only embeddings and output heads changes those hashes and breaks equivalence.

One viable adaptation stores token-derived operands as parameters:

```text
T[pi(t), j] = f_j(t)
hash_head = original_reduce(mix(T[u_now, 0], T[u_prev, 1], ...))
feature = feature_table[hash_head]
```

For example, the original `f_j(t)` may be machine-integer multiplication, `mix` XOR, and `reduce` a per-head remainder plus offset. Constructing `T` once lets the server compute independently from transformed IDs without per-token client callbacks. Do not introduce this table for a model without PLE.

**`T` is a secret equivalent to the complete mapping and must not be deployed as plaintext parameters.** If `f_j(t) = a_j * t mod 2^w` and `a_j` is odd, a multiplicative inverse directly recovers `t`. Renaming the table, splitting columns, or merging it into ordinary weights does not change this property. Moduli from multiple heads may also allow CRT recovery of mixed operands; original hash indices must stay on the device too.

This design allows the necessary mapping-equivalent relationship only as **sealed model parameters**, without an additional plaintext inverse table. Parameter loading and all subsequent hashing execute on the device.

## Hash semantics must match exactly

Extract the following semantics from the original implementation. Do not fix n-gram length, head count, vocabulary size, layer index, or integer width:

- Integer overflow width, signed interpretation, multiplication/XOR order, and remainder behavior for negative values.
- Whether EOS resets earlier context, and which padding/start tokens are used.
- Packed-prefill request boundaries, empty requests, padding slots, and chunked context.
- Context updates during decode, prefill, speculative verification, cancellation recovery, and cache hits.
- Whether TP ranks duplicate index computation, global/local row offsets, and the actual final-row count in each shard.

Compare every boundary against a trusted CPU reference first, then compare the device kernel. Online sealed mode must reject CPU hashing, CPU-small fast paths, CPU-offload workers, plaintext indices in disk-cascade paths, and implicit fallbacks. Adapting decode while missing prefill is insufficient.

## PLE feature tables and projections

Each head's feature dimensions may receive an independent permutation and sign transformation. With column vectors, use `f_private = A f`, where `A` is an invertible signed permutation. Transform every subsequent projection `W` to `W_private = W A^-1`, including all key/value branches and any other feature consumers.

The feature table may retain its original hash-row ordering without an additional row-permutation table. Coordinate transformation alone is not strong encryption; the feature table still requires sealing. Do not stack unverified obfuscation layers merely to make it look more hidden.

For quantized parameters:

- Determine the head from the actual global row; do not assume a file shard corresponds to one head.
- Preserve and verify scales/zero points, group/block axes, padding, and cross-shard boundaries. These auxiliary values may also reveal transformations.
- Sign-bit manipulation of IEEE-style floating point is valid only for a confirmed encoding. Test the exact FP8 variant, NaNs, saturation, and signed zero. Do not copy sign-bit XOR behavior into symmetric/asymmetric integer quantization.
- A feature-axis permutation may cross quantization groups; the original scales cannot simply remain unchanged. Prefer lossless rearrangements. If requantization is needed, measure and disclose the error rather than calling the result bit-exact.

When the complete feature table is too large, retain only authenticated ciphertext on the host. Device gather decrypts accessed rows, dequantizes them, and produces transformed features. The host must not receive original hash-row indices, decrypted rows, or hash operands. See [sealed-runtime.md](sealed-runtime.md) for random-access counter details.
