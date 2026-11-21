# Notices for the retained P05 Python execution archives

The two original GitHub workflow archives in `archives/` contain the Python
package, native comparison executables, kernel module and five-library SimX
closure tested at `e1420fd550f716df33a2556057b7086a03032cbe`. These notices and
the accompanying `licenses/` directory form part of this evidence distribution.
Keep them with the archives when redistributing this packet. The archives retain
their original bytes and provider digests; adding attribution here does not
rewrite a historical execution artifact.

## Project and upstream attribution

AI-GPU is derived from [Vortex](https://github.com/vortexgpgpu/vortex). The
Vortex contributors' copyright and source attribution remain in the repository,
including the [root README](../../../../README.md) and unchanged
[Apache License 2.0](../../../../LICENSE). A byte-identical license copy is
also provided [beside these archives](licenses/LICENSE-Apache-2.0.txt).
The Python binding and managed runtime carry the same project license. The
separately identified components below retain their own notices and terms.

## Components represented in the bundle

| Component and recorded source | Relationship to the retained artifacts | Notice |
|---|---|---|
| [Ramulator 2](https://github.com/CMU-SAFARI/ramulator2/tree/e62c84a6f0e06566ba6e182d308434b4532068a5), commit `e62c84a6f0e06566ba6e182d308434b4532068a5` | `libramulator.so`; `libramulator-vortex.so` builds its GDDR6 source through the project's `third_party/Makefile` | [MIT; SAFARI Research Group at ETH Zurich and Carnegie Mellon University](licenses/LICENSE-Ramulator2.txt) |
| [Berkeley SoftFloat Release 3e](https://github.com/ucb-bar/berkeley-softfloat-3/tree/b51ef8f3201669b2288104c28546fc72532a1ea4), commit `b51ef8f3201669b2288104c28546fc72532a1ea4` | The identified `softfloat.a` is linked into `libsimx.so` by the recorded SimX build recipe | [Berkeley three-clause notice, 2011–2018](licenses/LICENSE-SoftFloat-3e.txt) |
| Project `sw/common/softfloat_ext.cpp` at the tested commit | SoftFloat-derived implementation compiled into SimX | [Original Berkeley notice, 2011–2016](licenses/LICENSE-SoftFloat-extension.txt) |
| [yaml-cpp 0.7.0](https://github.com/jbeder/yaml-cpp/tree/0579ae3d976091d7d664aa9d2527e0d0cff25763) | Ramulator's declared dependency, configured as a static library; headers used by SimX and the extension | [MIT; Jesse Beder](licenses/LICENSE-yaml-cpp-0.7.0.txt) |
| [spdlog 1.11.0](https://github.com/gabime/spdlog/tree/ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36) | Ramulator's declared dependency; its default build is static and its headers are included by the native build | [MIT; Gabi Melman, including its fmt dependency notice](licenses/LICENSE-spdlog-1.11.0.txt) |
| fmt 9.1.0 bundled in the pinned spdlog source | Formatting implementation used by spdlog; `FMT_VERSION` is `90100` | [Complete license comment from bundled `format.h`, including its optional exception](licenses/LICENSE-fmt-9.1.0-header.txt) |

The two submodule commits are recorded in each execution packet's clean source
checkout identity. The pinned Ramulator [CMake source](licenses/ramulator-CMakeLists.txt)
names `yaml-cpp-0.7.0` and `v1.11.0`. The upstream tag resolutions retrieved for
this review are retained in [yaml-ref.txt](licenses/yaml-ref.txt) and
[spdlog-ref.txt](licenses/spdlog-ref.txt). The pinned upstream `yaml.h`,
`spdlog/version.h`, bundled fmt `core.h` and `format.h` have exactly the sizes
and SHA-256 values recorded in the actual execution source inventory; see the
[header comparison receipt](licenses/header-match-checks.json).

These checks establish the declared upstream versions and matching sampled
headers. They do not reconstruct every transitive dependency compilation or
prove a reproducible build of the cached prerequisite libraries. The original
packets retain the three prerequisite artifact hashes, before/after source and
tool identities, and compiler records. Their provenance limitations remain in
the independent audit.

## Binary and installation boundaries

[Read-only ELF inspection](licenses/elf-inspection.json) records `DT_NEEDED`
and search paths without executing any retained binary. The external system
dependencies named by these ELF files are `libstdc++.so.6`, `libgcc_s.so.1`,
`libm.so.6`, `libc.so.6`, and `ld-linux-x86-64.so.2`. Those system libraries and
the Python interpreter are identified requirements, not copied libraries in
these archives.

The hosted bound Python extension records
`RUNPATH=/opt/hostedtoolcache/Python/3.12.14/x64/lib`. `libsimx.so` records the
original build checkout's Ramulator directories; the dispatcher and backend
record `$ORIGIN`. The installed launcher and loader checks qualify the named
five-library project closure in the recorded environment. These facts do not
establish a manylinux wheel, arbitrary-host portability, an absence of search
paths, or a fully archived operating-system runtime.

The kernel link command names static C/compiler support libraries and uses
section garbage collection. The retained [FP16](licenses/fp16-kernel-symbols.txt)
and [BF16](licenses/bf16-kernel-symbols.txt) ELF symbol tables show the project
CTA startup, matmul entry and argument decoder, with no separate dynamic
dependencies. Merely naming a static archive on the link line does not show
that all of its code is present in this small kernel. The full toolchain is
not redistributed by this evidence packet.

## Review scope

The notices above were retrieved from the specified primary upstream sources
or copied from the exact project revision. The [source manifest](licenses/sources.json)
records their locations, byte sizes and hashes; the spdlog notice preserves
its original CRLF bytes. This is a bounded attribution and artifact inspection,
not a comprehensive legal clearance or authentication of binary authorship.
It does not change any license, grant trademark endorsement, waive provenance
limits or certify untested configurations. No model weights, PDK collateral,
commercial IP or toolchain archive has been added by this review.
