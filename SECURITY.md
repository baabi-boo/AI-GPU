# Security policy

## Experimental support boundary

AI-GPU is a Vortex-derived research and development project, not a qualified
production accelerator. Repository contents and a passing governance check do
not establish host isolation, safe handling of hostile kernels, multi-tenant
security or secure firmware/update behavior. See [project status](docs/project/status.md)
for accepted evidence and [release policy](docs/project/releases.md) for scope.
No supported-version security window or response-time commitment is established
by this setup. A future release must state its tested support envelope explicitly.

Treat kernels, model importers, build inputs, runtime components and bitstreams
as trusted code unless the exact release proves a stronger boundary. The native
runtime exposes device buffers, host-memory access and asynchronous queues;
available API error codes or memory flags alone do not prove isolation. DMA,
malformed descriptors and device reset may affect the host or unrelated work.
Do not deploy an experimental board on a sensitive or shared production host.

Use a dedicated authorized development environment, least privilege, controlled
device access and known source/toolchain inputs. Platform isolation such as an
IOMMU must be configured and verified for the actual host; its presence must not
be assumed. Do not run untrusted kernels or bitstreams, probe unrelated memory,
or energize/modify hardware without qualified supervision and authorization.
P08's [threat/failure model and tests](docs/project/phases/p08-reliability.md)
are planned qualification work, not guarantees already supplied by this policy.

## Reporting a suspected vulnerability

1. Record the affected full commit, configuration, platform and observed impact.
   Preserve a minimal authorized reproduction and sanitized logs privately.
   Do not include credentials, personal data, proprietary IP or sensitive host
   memory. Avoid destructive testing or tests outside your own authorization.
2. Check this repository's Security tab. **If private vulnerability reporting is
   enabled**, use its reporting form. This document does not claim that the
   feature is enabled or monitored.
3. If no private reporting route is available, use an existing verified private
   channel to a repository maintainer. If none exists, open a minimal issue asking
   for a confidential reporting channel without exploit details, sensitive logs
   or working attack code. Do not guess an email address or send secrets to an
   unverified contact.
4. Agree on disclosure and remediation with the maintainer. Do not publish
   sensitive details merely because a report or proposed fix exists. Keep a
   sanitized public summary separate from restricted reproduction evidence.

## Maintainer handling

Verify the reporting channel and affected versions, acknowledge when able, and
assess host/device impact and immediate containment. Keep sensitive evidence
restricted; arrange an upstream report when inherited Vortex code is affected.
Record the root cause, a targeted regression test and independent review without
weakening existing gates. Re-test the declared supported configurations and
coordinate the advisory and corrected artifact with the reporter as appropriate.

Before making security-support claims, assign an actual responder, confirm a
working confidential channel and publish a realistic supported-version policy.
An unresolved critical finding blocks the affected release claim. A proposed
patch, agent review or test on one simulator does not prove all boards are safe.
