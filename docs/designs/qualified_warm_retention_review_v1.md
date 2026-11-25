# Qualified warm retention review v1

Contract ID: `p06-qualified-warm-retention-review-v1`.

The [reader](../../ci/project/p06_qualified_warm_retention.py) and
[inspect/restore CLI](../../ci/project/p06_qualified_warm_restore.py) validate an
already-decrypted retention tar and optionally restore its exact bytes into a
fresh private directory. The accepted format is the deterministic output of the
[encryption producer](../../ci/project/p06_qualified_warm_encrypt.py), whose
manifest contract is `p06-qualified-warm-encrypted-retention-v1`.
The [operator guide](../project/p06-hosted-warm-guide.md) covers download,
ciphertext checks, private decryption and subsequent independent replay; the
[review audit](../project/p06-retention-review-audit.md) records scoped evidence.

## Trust and result scope

Use separately trusted reader code. The archive, manifest, optional public
summary and every retained payload are untrusted data. Inspection and restore
perform no decryption, network operation, subprocess launch, inner-archive
extraction or retained-code execution. ZIPs, scripts, reports and receipts are
preserved as opaque bytes, including malformed reports and failed or partial
attempts. Retention verification does not classify a complete native original or
reconcile successful packaging, invocation, upload or provider status.

The caller must select a lowercase 64-hex SHA-256 of the **plaintext tar** and
an exact lowercase 40-hex expected revision. Both must match. These inputs bind
local consistency to the caller's selection; they do not authenticate producer
origin or prove that retained work ran at the advertised revision. The generic
producer permits `expected_revision=null`; that is valid producer output but
cannot satisfy this exact-revision route and fails with `revision-mismatch`.

Stop writers before review. Repeated descriptor, pathname, identity and digest
checks detect observed changes; they cannot exclude every malicious same-user
concurrent writer. Recorded development checks ran on Linux with POSIX
descriptor APIs and CPython 3.12.14. Other platforms and Python versions are
not qualified by those checks.

## Manifest and bounds

`manifest.json` is the first regular member. Its object has exactly these keys:

| Key | Required value |
| --- | --- |
| `schema_version` | Exact integer `1`; Boolean values are rejected. |
| `contract_id` | `p06-qualified-warm-encrypted-retention-v1`. |
| `expected_revision` | Producer revision string or null; this route requires equality with the selected revision string. |
| `directories` | Sorted string list beginning with the unique empty string, denoting the input root. |
| `files` | Strictly path-sorted list of objects with exactly `path`, `size_bytes`, `sha256`. |

File paths are nonempty; sizes are exact nonnegative integers, excluding
Booleans; file hashes are lowercase 64-hex strings. JSON must be strict UTF-8,
with no duplicate keys at any level, floating-point tokens or nonstandard
constants. Manifest bytes must equal sorted compact JSON with ASCII escaping
and exactly one terminal LF, as emitted by the producer.

Files and directories share one namespace with exact and Unicode casefold
uniqueness. Every non-root entry has an explicitly declared directory parent.
Names are NFC, strict UTF-8 relative paths: no empty, `.` or `..` components,
backslash, colon, ASCII controls below 32 or DEL. Names are never trimmed or
normalized. Spaces, `=`, hidden names and valid non-ASCII characters remain
supported, as do empty files, empty directories, an entirely empty input tree
and a retained file named `manifest.json` beneath `private/`.

| Quantity | Bound |
| --- | ---: |
| Files plus directories, including the root | 40,000 |
| One retained file | 268,435,456 bytes (256 MiB) |
| Sum of retained file bytes | 1,073,741,824 bytes (1 GiB) |
| Manifest body | 16,777,216 bytes (16 MiB) |
| Optional summary body | 65,536 bytes (64 KiB) |
| Manifest-relative path | 4,096 UTF-8 bytes; 128 components; 255 bytes per component |
| Conservative plaintext archive cap | 1,336,299,520 bytes |
| One payload read/copy chunk | 65,536 bytes (64 KiB) |

The archive cap includes manifest, headers, PAX records, padding and terminators;
the exact expected archive length is also checked. The reader retains a bounded
manifest and entry index, never the complete archive in memory. These retention
bounds do not admit native work or change its resource budgets.

## Exact producer tar encoding

The accepted stream is uncompressed PAX-format tar in this order: regular
`manifest.json`, root `private/`, then all remaining files and directories in
one merged Python string-sorted order. The reader constructs fresh trusted
`TarInfo` headers with producer metadata and compares their serialized bytes;
it does not accept arbitrary tar encodings or normalize parsed member names.

Regular members use type `0`, mode `0600`; directories use type `5`, mode
`0700` and size zero. UID, GID and mtime are zero; owner, group and link names
are empty. Raw directory names include one trailing slash. The ordinary
USTAR headers, octal fields, checksums and remaining metadata must exactly
match the producer's `PAX_FORMAT`, UTF-8, strict-error serialization.

A non-ASCII effective name or one longer than 100 characters uses the
producer's immediately preceding local PAX `x` header, named `././@PaxHeader`,
with exactly one byte-length-prefixed UTF-8 `path` record. Its following ordinary
header uses the producer's ASCII-replacement, 100-byte fallback name. These
extension records are metadata, not extra restored entries. Directory slashes
and the `private/` prefix are added after manifest-relative path validation;
a maximal raw directory path can therefore be 4,105 UTF-8 bytes. Global or
unknown PAX records, GNU extensions, sparse members, links and special files
cannot match the expected bytes and are rejected.

Every declared regular payload is read and checked against its size and
SHA-256. Payload padding must be zero. Two zero terminator blocks and zero
padding to the exact 10,240-byte record boundary are mandatory. Missing,
duplicate, reordered or extra members, malformed headers, nonzero padding,
truncation, concatenated archives and extra all-zero records are rejected.
The complete plaintext SHA-256 and bytewise EOF are checked before admission.

## Optional public summary

`summary` / `--summary` is an existing encryption-summary **input**. Its exact
keys are `schema_version`, `contract_id`, `expected_revision`, `outcome`,
`encryption_passed`, `file_count`, `directory_count`, `input_bytes`,
`ciphertext_bytes` and `ciphertext_sha256`. Version and counts require exact
integers; the contract must match the producer, outcome must be `pass`, and
`encryption_passed` must be Boolean `true`. Revision, file count, directory
count (including the root) and input bytes must equal the validated manifest.
Duplicate keys, floating-point tokens and malformed JSON are rejected; summary
whitespace and equivalent JSON escaping need not be canonical.

Ciphertext size is checked only for a positive bounded integer and its hash
only for lowercase 64-hex syntax. No ciphertext is supplied to this reader:
`summary_checked=true` does **not** verify actual ciphertext bytes, their hash,
size, decryption relationship, origin or successful delivery. In particular,
`ciphertext_sha256` cannot replace the caller-selected plaintext tar digest.

## Filesystem lifecycle and failure retention

Archive, summary and output arguments use canonical absolute paths. Input
ancestors are opened component by component with directory/no-follow flags;
the final input must be a nonempty bounded regular file with one link. Named
and descriptor identities must agree, and the input descriptors remain open
through use. Symlinks and special inputs are rejected without following them.

Full archive, revision, digest, inventory and optional-summary validation, plus
a further source-stability check, precede output creation. The output parent
must already exist. The destination must be absent: an existing empty directory,
file or dangling symlink fails; there is no merge or overwrite option. Lexical
input/output overlap and observed ancestor or created-directory aliases fail.

Restore creates one root containing the exact manifest bytes and the declared
`private/` tree. A direct local original can be at
`private/qualified-warm-original.PRIVATE.zip`; the hosted selection uses
`private/packet/qualified-warm-original.PRIVATE.zip`. Actual manifest paths are
preserved without changing the packaging layout.
All traversal uses held no-follow directory descriptors and
verified created-directory identities. Files are created relative to their
owned parents with `O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`; short writes
are retried. Directories are explicitly `0700` and files `0600`, independent
of umask. Archive ownership, timestamps and executable behavior are not applied.
Open-descriptor usage is bounded by path depth rather than inventory size.

An exclusive `.restore-incomplete.PRIVATE.json` marker is written first, outside
`private/`. Copied files are fsynced and reread to check type, identity, mode,
single-link count, size and hash. Complete output membership, directories and
the original named root are rechecked. The owned marker is removed only after
verification; the tree, source hashes and root identity are checked again,
directories are fsynced, and normal reader-context exit rechecks the inputs
before the API returns success. No persistent pass receipt is created.

Failures after creation retain the owned partial output. There is no recursive
cleanup or removal of an unrelated replacement tree; late marker recreation
is exclusive and best effort. Filesystem failure or abrupt termination can
prevent marker creation, final checks or durable completion. Output existence
and marker absence do not prove success. Restore is not an atomic crash
transaction, and concurrent same-user mutation remains outside hard exclusion.

## API, CLI and reports

```python
inspect_archive(archive, expected_sha256, *, expected_revision, summary=None)
restore_archive(archive, expected_sha256, *, expected_revision, output_dir,
                summary=None)
```

The reader also exposes `RetentionArchive(...)` with the inspect arguments as
a context manager. `.manifest` and `.entries` return defensive snapshots;
`.manifest_bytes` exposes the exact validated bytes. Entries are relative to
`private/`, with root `""`; files include validated payload offsets.
`.copy_file(name, output_fd)` streams to a caller-owned empty single-link regular
descriptor at offset zero and rechecks copied source bytes. It resolves no
output path; the restore layer owns private creation and output rereading.
`.assert_unchanged()` rehashes the complete archive and optional summary.
A `.report()` obtained inside the context is provisional until normal context
exit succeeds; both convenience functions return only after that exit.

```text
python3 -B ci/project/p06_qualified_warm_restore.py inspect \
  --archive ABSOLUTE_TAR --sha256 PLAINTEXT_SHA256 \
  --expected-revision EXACT_REVISION [--summary ABSOLUTE_SUMMARY]
python3 -B ci/project/p06_qualified_warm_restore.py restore \
  --archive ABSOLUTE_TAR --sha256 PLAINTEXT_SHA256 \
  --expected-revision EXACT_REVISION --output-dir ABSENT_ABSOLUTE_DIRECTORY \
  [--summary ABSOLUTE_SUMMARY]
```

Normal CLI operations emit sanitized JSON and exit 0 on success or 1 on failure.
API errors use fixed `RetentionError.code` / `RestoreError.code` values; CLI
retention errors become `retention-rejected`, with no retained names, paths,
payloads, user arguments or arbitrary exception strings in the diagnostic.
Success reports give revision, plaintext identity, retention counts and
`summary_checked`; restore additionally sets `restoration_completed=true`.
`retention_verified=true` establishes only the described local consistency.
Every report keeps `native_execution="not_run"`, `retained_code_executed=false`,
`origin_authenticated=false`, and native, performance and phase acceptance
false. Failed or partial retained work stays failed or partial after restoration.
