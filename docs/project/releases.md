# Release and compatibility policy

AI-GPU is an experimental Vortex-derived accelerator project. A published source
revision is not a production GPU, a validated board or an NVIDIA-compatible
product. This policy defines future release obligations; it does not assert that
any release class below has been qualified. Consult [status](status.md) and
[roadmap.json](roadmap.json) for actual accepted work.

## Release classes

| Class | Required evidence before using the label | Permitted claim and boundary |
|---|---|---|
| Source preview | P00 foundation acceptance, exact source revision, checks and explicit not-run list | Inspectable development source and plans; no new GPU execution or performance claim |
| Verified simulation preview | Accepted P01–P04 evidence for the declared native model/configuration; P05 also required if a Python/framework package is included | The named workload works in the named simulator; neither physical speed nor arbitrary-model support |
| FPGA pilot | Accepted P07 and its dependencies, identified board/bitstream and physical results including the initial one-hour soak | A bounded physical prototype; not the hardened release, ASIC performance or multi-tenant security |
| Hardened experimental FPGA release | Accepted P08, including its P05/P07 dependencies, fault/recovery tests, 24-hour physical soak and clean installation | The tested experimental support envelope; not production or safety-critical certification |
| Silicon evaluation release | Accepted P10/P11, qualified sign-off, explicit human manufacturing approval and measured devices | The measured silicon revision and operating envelope; not unmeasured production yield or market parity |

Component-only previews may report narrower verified results, but must name the
component and cannot borrow an end-to-end class they have not earned. P09
training/multi-device research is separately gated and is not required for the
bounded inference-silicon path. Every claim must satisfy the relevant
[acceptance policy](acceptance.md), not merely match a tag name.

## Release packet

The release lead assembles a reviewable packet tied to one frozen source tree:

1. **Identity:** target repository, full source commit and tree, release identifier,
   change summary and predecessor. Record all submodule commits, configuration
   files/overrides and build inputs. Preserve the Vortex origin and attribution.
2. **Tool provenance:** the values in [VERSION](../../VERSION), actual installed
   compiler/simulator/tool versions, package/container identities and hashes of
   downloaded inputs. A moving tag or package name alone is insufficient.
3. **Artifact manifest:** name, purpose, size and SHA-256 for each distributed
   source archive, executable, library, kernel, package and bitstream. Associate
   each artifact with its producing command and tested configuration.
4. **Dependency inventory/SBOM:** component/version/source/license information for
   bundled code, runtime dependencies, submodules and tool-produced redistributable
   assets. Inventory model/tokenizer/fixture provenance separately. Preserve
   [LICENSE](../../LICENSE), upstream notices and applicable third-party terms;
   the repository license does not automatically cover every dependency or model.
5. **Compatibility matrix:** tested host OS/architecture, runtime/API version,
   toolchain pin, XLEN, hardware features, tensor implementation, precision and
   numerical-contract version, operator/model signatures, and unsupported cases.
   Python/framework versions appear only when that path is included and tested.
6. **Evidence:** exact commands, raw result manifests, accepted gate IDs, independent
   review dispositions, failures and limitations using the
   [evidence format](evidence/README.md). Describe native versus DPI arithmetic,
   processor RTL versus full AFU integration, and emulation versus physical runs.
7. **Operations:** clean installation/reproduction, resource budget, safe startup,
   timeout/reset/recovery behavior, known issues and the next bounded work item.
   Include the applicable [security boundary](../../SECURITY.md).

For physical releases also pin board/device revision, platform/firmware, memory
map and usable capacity, bitstream hash, achieved clock and operating conditions.
Silicon packets include package/board revisions, qualified sign-off references,
manufacturing-test coverage and actual sample counts for any yield claim.
Benchmark claims follow the [measurement policy](benchmarks.md); theoretical,
simulated and physical values must not be combined into one reported result.

Do not bundle large toolchains, waveforms or weights just to make a packet look
complete. Use authorized artifact storage with stable identifiers and hashes,
while keeping compact manifests and accessible evidence references here. Do not
publish credentials, signed access URLs, proprietary PDK/IP, confidential quotes
or materials without redistribution permission. A checksum is not permission.

## Reproduce, review and publish

- Freeze the declared acceptance bounds before the release evaluation. Re-run
  affected tests after changes to source, configuration, precision or tools;
  do not transfer an old pass to a materially different artifact.
- Reproduce installation and the declared test matrix in a clean supported
  environment following the [developer guide](developer-guide.md). Record exact
  steps and results. Distinguish functional reproducibility from byte-identical
  builds; if tool nondeterminism prevents identical binaries, document it and the
  verified comparison method rather than claiming a reproducible hash.
- Apply the inherited [review policy](../review/code-review-policy.md). Resolve
  required findings, confirm all relevant phase evidence and explicitly report
  failed, blocked or unexecuted CI jobs. Governance checks do not replace GPU tests.
- Obtain the actual maintainer release decision. FPGA access, paid services,
  commercial IP, procurement and manufacturing require their own human authority;
  an agent review or repository tag cannot grant it.
- Verify the intended repository and current branch head before publication;
  preserve concurrent changes. Publish the immutable release identity, artifacts,
  checksums, limitations and review packet, then read back the published state.
- Update [status](status.md), [backlog](backlog.md) and phase evidence with what
  was actually delivered. A later correction receives a new revision and a clear
  supersession notice; retain prior results for traceability.

## Stop, withdraw and resume

Unexplained numerical differences, hidden CPU fallback, missing native-datapath
coverage, memory corruption, unsafe recovery, failed required soak tests,
unresolved critical security issues, incompatible artifacts or missing license/
human approval block the affected release class. Do not widen tolerances, edit
goldens, shorten the soak or conceal failures to ship.

If a released artifact is found unsafe or invalid, identify affected revisions,
document the limitation and recommend discontinuing the affected use. Coordinate
sensitive details under [SECURITY.md](../../SECURITY.md), preserve failure evidence
and qualify a corrected artifact before restoring the claim. No support window,
response-time guarantee or production-service commitment is established by this
setup; any future commitment must name an accountable maintainer and resources.
