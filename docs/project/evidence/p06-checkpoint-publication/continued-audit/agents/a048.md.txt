# A048 — launcher packaging and retained-source scope audit

## Disposition and scope

No concrete missing file binding, package payload gap or false historical-source reuse was found for the current launcher change. The new `_run_child` implementation remains inside an already inventoried file. The added `signal` and `threading` imports are Python standard-library modules; they add no repository-local helper or third-party dependency. No source-path inventory, manifest membership or historical replay snapshot contract needs to be expanded merely for this same-file change.

Read-only source inspection at HEAD `d31e8879e7c248b1a72615128882533ccdd0b3b4`, with the launcher change still in the working tree. Observation time: 2026-11-26T07:04:18.451787+00:00. No tests, package builds, installation, native execution, downloads, commits or pushes were performed. This is a source audit, not fresh package/native qualification.

## Source evidence

1. **The launcher is already part of the binding identity.** `python/vortex_ai/_bundle.py:17–28` lists `python/vortex_ai/launch.py` in `SOURCE_PATHS`. `source_inventory` and `inventory_digest` at lines 137–142 hash the entire file, not selected functions. Manifest checks at lines 176–180 require the same closed ordered membership and its exact digest. `build_binding` at lines 261–266 compares the current source inventory with the qualified bundle. Consequently the new launcher bytes change `binding_source_sha256` automatically and an old bound bundle cannot silently qualify the changed source.

2. **Package preparation checks both source membership and bytes.** `MANIFEST.in:9` already includes the launcher. `setup.py:56–72` compares the actual Python/native source-file set with the declared binding set. `BuildIdentity` at lines 125–180 derives the source identity, verifies retained sdist inventory/header/manifest pins, and refuses a replacement bundle pin. `PinnedBuildExt` stages checked source bytes and forces a fresh extension build (lines 202–241); the sdist path also checks the staged inventory (lines 260–276). The source remains a single shipped Python module, so the new helper function requires no extra payload member.

3. **Current execution packets retain the changed module automatically.** `ci/project/p05_execute.py:89–97` unions `_bundle.SOURCE_PATHS` into the source snapshot; lines 358–362 retain those source bytes. `ci/project/p05_bundle.py:299–304` records each binding source, lines 431–437 put that inventory/digest into the bundle manifest, and lines 460–462 recheck source and binding identities after copying. No new local import escapes those collections.

4. **Wheel and installed-route checks continue to bind the complete launcher.** Existing packaging tests explicitly check launcher inventory/manifest membership (`test_p05_packaging.py:96–107`), missing launcher inputs, missing wheel members and stale launcher bytes (`:279–287`, `:510–541`, `:545–562`). These tests were inspected, not executed. P05 installed execution starts the installed launcher through the same `python -I -B -m vortex_ai.launch --bundle ... -- SCRIPT ...` CLI (`p05_execute.py:555–561`; `p05_torch_execute.py:756–764`). The change preserves that CLI. Installed native runs remain necessary to qualify the new published source; this audit does not substitute for them or establish native cancellation behavior.

5. **Historical replay compares retained bytes to the historical records.** `ci/project/p05_replay_native.py:81–91` already includes the launcher in the frozen Python retained-source set. Lines 214–226 reconcile retained member bytes with the recorded source inventory and helper identities. `p05_replay_installation.py:47–57` independently includes the launcher in its binding source set; lines 166–183 require closed membership, the recorded source digest and matching retained source bytes in the Python/framework views. Its wheel reconciliation (`:236–267`) derives expected package members from those bound records and checks complete source bytes. This does not read the current launcher and substitute it into old execution evidence. The separate historical acceptance-reference updates are being reviewed by A043/A045/A046; no numerical or old-source claim is added here.

6. **Frozen native scope stays separate.** The qualified-warm proof lists 69 measurement source paths; zero start with `python/` ([]). This confirms the parent’s stated projection boundary. It does not imply that the revised Python package is already accepted or installed.

## Limits and follow-through

No additional package dependency is required by `signal` or `threading`; the project already requires Linux CPython 3.12 (`setup.py:202–206`, `pyproject.toml:11–14`). Historical wheels continue to contain their historical launcher. Using the new behavior requires a source-matched fresh package/bundle through the existing qualified producer and installation path. The current source inventories correctly enforce that boundary. No historical pin or replay source list should be rewritten to make an old wheel appear to contain this fix.

The source inspection found no reason to add native helper inventory entries for the new host test module. Unit-test discovery/governance should retain and execute that test under its own test-source mechanism; the package binding inventory covers shipped/build inputs rather than every repository test.

## Inspected source identities

- `python/vortex_ai/launch.py` — SHA-256 `01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128`
- `python/vortex_ai/_bundle.py` — SHA-256 `cf438f291359314844b6489545ad1b263639a36706ae3b86f94d9832c6ee4679`
- `setup.py` — SHA-256 `697024fc8074f31aa9def1ebeb2d923104ff731f0dcfb80dbeefc6974d267e65`
- `MANIFEST.in` — SHA-256 `aa88954e1e848cde7778e7a4a1e4c0743d638088f1ce183979920adae53c6eb7`
- `ci/project/p05_execute.py` — SHA-256 `18f63ebd5bb04fbe9bcdf094d6d2464dbd8196ba3602d064f9b27ee87f9f7ef4`
- `ci/project/p05_bundle.py` — SHA-256 `209610324c3bb1d9f4ae9b833759bec3c7823d7590d5d3bc8e3bfd414373000c`
- `ci/project/p05_replay_native.py` — SHA-256 `88263ee6c53a0c95ba97dfdd8ee42c244ba5906c08b6328080db44811dbd4712`
- `ci/project/p05_replay_installation.py` — SHA-256 `759c6249ed503b9da66b077364fe481b52ac048eb29cecde1bf793bdaf14efc9`
- `ci/project/p05_torch_replay.py` — SHA-256 `737eafad91bccc251039bade0ee7af4ce976bbda3d983361d240420cd8158dd3`
- `ci/project/test_p05_packaging.py` — SHA-256 `5629c28a88b459d7e7637978193b353b809b229ba863c9421fefb8c298aa218d`
