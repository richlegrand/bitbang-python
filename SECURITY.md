# Security Policy

## Reporting a vulnerability

**Please report privately, not as a public issue.**

Use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/richlegrand/bitbang-python/security/advisories/new).
It is private to the maintainers, and it gives us a place to develop and review a fix with
you before anything is public.

If you cannot use GitHub, email **security@bitba.ng**.

Useful to include, though a partial report is far better than none:

- What an attacker gains, and what they need to already have
- Affected version or commit
- Steps to reproduce, or a proof of concept
- Any suggested fix

## What to expect

BitBang is maintained by a very small team, so an honest statement rather than a service
level agreement: we aim to acknowledge a report within a few days and to keep you updated
as we work through it. Complex issues take longer, and we will say so rather than go quiet.

We are glad to coordinate disclosure, agree an embargo date, and credit you in the
advisory. If you would rather not be credited, say so.

## Scope

This is the Python implementation of BitBang. Its security model matches the Go client: the
connection is end-to-end encrypted between the peer and the device, and the signaling
server routes without being able to read the traffic or insert itself into it. Anything
that breaks that is in scope.

**In scope**

- Any party other than the two endpoints reading, modifying, or injecting into session
  traffic, including the signaling server or a relay
- Impersonating a device, or defeating the public-key verification that prevents
  man-in-the-middle
- Disclosure of an access code, PIN, or device private key
- Bypassing the PIN or any other access control
- Reading or writing files outside a shared directory
- Reaching a network target the operator did not authorize
- Remote code execution on the device
- Resource exhaustion triggered by a peer, where a bounded input causes unbounded
  allocation or work
- Unsafe deserialization, or a dependency used in a way that introduces one of the above

**Out of scope**

- The signaling server observing connection metadata such as timing, size, or which
  identifiers are connecting. This is a documented property of the design, not a defect.
- Anyone holding a valid access link having the access that link grants. Links are
  capabilities. Ways to obtain a link you were never given are in scope.
- Attacks that require an already-compromised device, or an operating system account on the
  machine running the listener
- Volumetric denial of service. Bugs where a small input causes disproportionate resource
  use are in scope, as above.
- Vulnerabilities in third-party dependencies with no demonstrated reachable path from this
  code. Please do report it if you can show the path.
- Automated scanner output with no working proof of concept

A finding here often applies to [bitbang-cli](https://github.com/richlegrand/bitbang-cli)
as well, since the two implement the same protocol. Mention it if you have checked, but do
not feel obliged to; we will check both.

## Supported versions

BitBang is pre-1.0 and moves quickly. Fixes land on `main` and go out in the next release.
Only the latest release is supported; please confirm against it before reporting.

## Safe harbor

We will not pursue or support legal action against anyone who makes a good-faith effort to
follow this policy: research on your own devices and accounts, no access to or modification
of other people's data, no degradation of service for others, and a reasonable window to
fix before public disclosure. If you are unsure whether something is in bounds, ask first.
