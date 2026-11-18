# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Report privately through GitHub's **"Report a vulnerability"** button on this repository's **Security** tab (private vulnerability reporting).

Useful details: affected version, how to reproduce, and impact. Please use made-up examples, never real secrets or private code.

We aim to acknowledge reports within 7 days and to agree on a fix and disclosure timeline with you.

## Supported versions

VerifyPR is pre-release. Only the latest release on the `main` branch receives security fixes until v1.0.

## Areas of particular interest

- Prompt injection through diffs, PR text, tickets, or agent claims changing VerifyPR's results
- Secrets or API keys leaking into logs, reports, or requests
- Any default command writing to the repository or git state
- The local web UI being reachable from other machines or accepting requests without its session token
