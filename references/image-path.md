# EtC images and spatial relationships

## Client processing order

1. Follow the original processor's EXIF orientation, color/alpha, resize/crop, padding, and multiresolution tiling semantics. Original image files and metadata remain on the client.
2. Construct pixel blocks using the model's actual patch specification. Main blocks must match patch input domains; discover subblock dimensions, channel count, temporal axes, and merge axes from the architecture.
3. Within every main block, apply the same seed-derived subblock permutation, rotations, flips, channel permutations, and optional intensity inversion. The same linear input channels must be handled by one fixed set of folded parameters. Do not change secret pixel transformations per image if fixed model parameters cannot cancel them.
4. Each image may use an independently randomized main-block order `q`, defined by `q[new_position] = old_raster_position`. Upload this order as **public** little-endian uint32 metadata.
5. Compress the protected pixels as lossless PNG. Upload the transformed PNG, `q`, grid, and token-placeholder offset, not the original image, filename, or EXIF.

Public main-block reordering supports computational repositioning; it does not hide layout. Protection comes from within-block transformations and parameter sealing, but still does not claim resistance to visual reconstruction. PNG compression follows the transformation and may produce a larger file than the original JPEG. Do not upload AES-randomized pixels expecting direct visual inference, or decrypt them back into original images on the server.

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

The server's decoded PNG buffer still contains EtC pixels. Only normalize and arrange them into transformed patches for the folded first projection.

Map `q` from original raster order into the model's native patch order. Some implementations pack patches by merge group, so native order cannot be assumed to equal raster order. Handle each image's base offset separately and never mix positions across images.

Choose an equivalent implementation:

- For permutation-equivariant visual layers with global attention, reorder absolute positions, RoPE cos/sin, and other metadata according to `q`. Continue computation in permuted order, then inverse-permute **features** before the original spatial merger.
- For local windows, convolutions, pooling, relative-position biases, or complex intermediate branches, restore **features** to native order immediately after the first projection, then run the original visual network. This may preserve equivalence more easily without reconstructing pixel buffers.

If permuted order is retained until the merger, also adapt window grouping, cu_seqlens, attention masks, relative biases, interpolation, deep-stack outputs, and cross-scale connections. Changing only RoPE is insufficient. Do not silently disable visual branches required by the original model.

Restoring the order of internal model features is allowed under the boundary that excludes attacks on those features. If the user also requires intermediate-feature confidentiality, revisit the stronger execution-isolation requirement.

## Input validation

Derive accepted PNG modes, patch size, grid, temporal length, merge constraints, maximum image count, and pixel limits from the authenticated profile. Check compressed size, PNG header dimensions, and decoding limits before decoding to prevent decompression bombs.

- The length of `q` must equal `patch_count * sizeof(uint32)`, with the complete expected value range and no duplicates.
- Dimensions must match the PNG size, grid products must not overflow, and position metadata must match blob counts.
- Image-placeholder ranges must be ordered, nonoverlapping, correctly sized, and filled with the transformed image token.
- Image hashes must include transformed bytes, position metadata, and profile; additionally isolate caches by tenant/session.
- Explicitly reject unsupported video, multiscale processing, or front-end structures. Do not send the input back to the default processor as an ordinary original image.

## Required validation

Compare first-layer outputs, final visual features, and downstream answers between the original processor and the EtC path. Check numerical equivalence as well as left/right, up/down, colors, text, small objects, duplicate images, image-order swaps, and nonidentical images. Unchanged classification accuracy does not establish unchanged spatial question answering.

Generate multiple public patch permutations for the same image and verify stable correctness. For performance comparisons, use a fixed synthetic test order so baseline and candidate receive identical protected bytes; do not change production-client randomness. Report tolerances for small floating-point differences caused by quantization or changed summation order.

See the [original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10098741/) for the background on jointly transforming EtC images and model projections. This design adapts that idea to generative visual paths with per-architecture validation; do not extrapolate image-classification experiments to every multimodal feature.
