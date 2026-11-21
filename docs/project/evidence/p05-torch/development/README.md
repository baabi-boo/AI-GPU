# Retained P05 framework development originals

This packet preserves prototype implementations, original failed probes,
corrected probes, source-scoped host tests and independent reviews. These are
development records; scripted native owners and compiled host fault runtimes
do not establish SimX arithmetic or hardware acceptance.

The index hashes exact retained bytes. Its optional `original_path` maps a
source Markdown filename to a `.txt` snapshot so historical relative links do
not become current documentation. Paths named `p05-torch-work` in original
reports refer to this packet root. Recorded commands retain their original
workspace provenance; they are not portable qualification commands.

The baseline suite ran on untouched `bdd3485243f820947df94f7962641d10f2169834`.
It failed one class setup when unchanged configure exceeded its 15-second
timeout; two class tests therefore did not run. The separate diagnostic does
not turn this failure into a pass or change that deadline. Fresh hosted source
tests and installed native/framework qualification are recorded separately.
