# EtC images and spatial relationships

## Client processing order

1. Follow the original processor's EXIF orientation, color/alpha, resize/crop, padding, and multiresolution tiling semantics. Original image files and metadata remain on the client.
2. Construct pixel blocks using the model's actual patch specification. Main blocks must match patch input domains; discover subblock dimensions, channel count, temporal axes, and merge axes from the architecture.
3. Within every main block, apply the same seed-derived subblock permutation, rotations, flips, channel permutations, and optional intensity inversion. The same linear input channels must be handled by one fixed set of folded parameters. Do not change secret pixel transformations per image if fixed model parameters cannot cancel them.
4. Each image may use an independently randomized main-block order `q`, defined by `q[new_position] = old_raster_position`. Keep this order secret and serialize it as little-endian uint32 values inside the image envelope.
5. Serialize the EtC tile as HWC RGB uint8 bytes followed by `q`. Authenticate and encrypt the whole payload using the v3 image contract before upload. Public metadata contains only validated geometry and token-placeholder information. Do not upload PNGs or clear patch order, original files, filenames or EXIF.

EtC block and pixel permutations preserve exploitable image statistics. Publishing the block order additionally exposes spatial layout. These operations and parameter sealing alone do not establish image confidentiality. The outer authenticated encryption is opened only on the GPU, producing still-transformed EtC pixels for the folded projection; AES ciphertext is never sent directly into the visual network. No original image buffer is reconstructed. Raw tile transport avoids requiring a PNG decoder on the GPU; account for its actual traffic cost.

## Equivalence with the first projection

Use column vectors throughout. Let `x` be the original normalized patch and define the protected normalized patch as:

```text
x_private = A x + c
y         = W x + b
W_private = W A^-1
b_private = b - W_private c
```

Then `W_private x_private + b_private = y`, without generating original pixels on the server.

For pixel range `[0,M]`, position/channel index `m(j)`, sign `s_j` equal to +1 or -1, and per-channel normalization parameters `mu`, `sigma`:

```text
p_private[j] = s_j * p[m(j)] + (1-s_j)*M/2
A[j,m(j)]   = s_j * sigma[m(j)] / sigma[j]
c[j]        = (s_j*mu[m(j)] + (1-s_j)/2 - mu[j]) / sigma[j]
```

When the mean is 0.5 and the standard deviation is identical everywhere, `c=0` and `A` is a signed permutation. Reordering projection columns and flipping weight signs is then sufficient. **Do not change the original model's mean/std merely to enable this shortcut.** General normalization requires the full affine correction; when the original layer has no bias, add an equivalent constant offset and validate it.

Handle channel, temporal, height, and width dimensions in the actual weight-flattening order. If a static image must be replicated into temporal patches, match the original processor's replication rules; this does not automatically support video. Quantized first layers require corresponding quantization-metadata transformations to avoid undisclosed accuracy loss.

## Spatial encodings and the merger

Authenticate the complete envelope on the GPU before using any decrypted data. Validate the secret permutation's range and uniqueness on the GPU; only a success/failure scalar may return to CPU. Normalize and arrange the decrypted EtC bytes into transformed patches on the GPU, then apply the folded first projection. Plaintext pixels and order must not pass through CPU tensors or IPC.

Map `q` from original raster order into the model's native patch order. Some implementations pack patches by merge group, so native order cannot be assumed to equal raster order. Handle each image's base offset separately and never mix positions across images.

Choose an equivalent implementation:

- For permutation-equivariant visual layers with global attention, reorder absolute positions, RoPE cos/sin, and other metadata according to `q`. Continue computation in permuted order, then inverse-permute **features** before the original spatial merger.
- For local windows, convolutions, pooling, relative-position biases, or complex intermediate branches, restore **features** to native order immediately after the first projection, then run the original visual network. This may preserve equivalence more easily without reconstructing pixel buffers.

If permuted order is retained until the merger, also adapt window grouping, cu_seqlens, attention masks, relative biases, interpolation, deep-stack outputs, and cross-scale connections. Changing only RoPE is insufficient. Do not silently disable visual branches required by the original model.

Restore internal features only on the GPU and keep them there through the visual merger, language-model input, caches and sampling. Opaque device handles may cross a CPU interface; embedding arrays and full image-conditioned logits may not. This excludes GPU/driver inspection and active runtime tampering; it does not provide confidential execution on ordinary hardware.

## Input validation

Derive patch size, grid, temporal length, merge constraints, maximum image count and pixel limits from the authenticated profile. Check envelope lengths before upload to the GPU; the plaintext length must be `3*width*height + 4*patch_count`. Bind geometry, image/tile indices, profile, connection challenge and token-blob digest into AAD.

- The decrypted length of `q` must equal `patch_count * sizeof(uint32)`, with the complete expected value range and no duplicates, checked on the device.
- Dimensions must match the expected RGB byte count, grid products must not overflow, and public position metadata must match blob counts.
- Image-placeholder ranges must be ordered, nonoverlapping, correctly sized, and filled with the transformed image token.
- Image hashes must include ciphertext, authenticated context, and profile; additionally isolate caches by tenant/session.
- Explicitly reject unsupported video, multiscale processing, or front-end structures. Do not send the input back to the default processor as an ordinary original image.

## Required validation

Compare first-layer outputs, final visual features, and downstream answers between the original processor and the EtC path. Check numerical equivalence as well as left/right, up/down, colors, text, small objects, duplicate images, image-order swaps, and nonidentical images. Unchanged classification accuracy does not establish unchanged spatial question answering.

Generate multiple secret patch permutations for the same image and verify stable correctness. For performance comparisons, fix the order only in the trusted harness so baseline and candidate receive identical EtC plaintext; encrypted envelopes may differ. Preserve production-client randomness and nonce uniqueness. Report tolerances for small floating-point differences caused by quantization or changed summation order.

Add captured-input reconstruction and repeated-image linkability regressions. A zero-match scan for original pixels does not establish resistance to statistical reconstruction. Check CPU memory for EtC data, secret forward/inverse order, visual features and raw/expanded image keys after real workloads. Reject a new encrypted path that later downloads plaintext intermediates to CPU.

See the [original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10098741/) for the background on jointly transforming EtC images and model projections. This design adapts that idea to generative visual paths with per-architecture validation; do not extrapolate image-classification experiments to every multimodal feature.
