# Sources and scope

These sources describe the underlying mechanisms and interfaces. Actual implementation details must follow the target machine's installed versions and this skill's equivalence and boundary checks. Publications do not replace deployment acceptance tests.

- [Covariant Obfuscation technical report](https://arxiv.org/abs/2603.01499): background on equivalent reparameterization. This skill uses the idea without applying the entire paper's method or white-box guarantees to every model.
- [Research on jointly transforming EtC images and visual projections](https://pmc.ncbi.nlm.nih.gov/articles/PMC10098741/): relationships between block transformations, model transformations, and compression. This skill defaults to lossless PNG and separately validates spatial semantics for generative vision.
- [NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final): the definition of GCM authenticated encryption. Parameter packages require full authentication and unique nonces.
- [vLLM general plugins](https://docs.vllm.ai/en/stable/design/plugin_system/): plugin registration and worker loading; check the deployed version's interfaces.
- [vLLM engine arguments](https://docs.vllm.ai/en/latest/configuration/engine_args/): skipping tokenizers, token-ID inputs/outputs, and runtime configuration. Do not blindly apply latest-version options to an older environment.

The general implementation preserves mechanisms and testing lessons without carrying over the original deployment's machine details, model names, secrets, certificates, performance figures, or resource addresses. Protocol constants, cryptographic parameters, and file-format versions define compatibility. Discover model dimensions, device configuration, and performance results anew.
