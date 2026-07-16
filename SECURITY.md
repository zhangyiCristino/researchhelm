# Security Policy

## Supported Version

Security fixes are developed for the current `2.x` line. Before the first `2.0.0` release, the implementation is pre-release and publication remains blocked until its documented release gates pass. Older versions may receive guidance, but no unsupported version should be assumed secure merely because a report has not been published.

## Credential and Privacy Boundary

ResearchHelm is limited to the project workspace and paths the user explicitly places in scope. It must not inspect Claude Code or Codex account/configuration directories, browser profiles or cookies, Git credential helpers, SSH or GPG private keys, cloud credential files, operating-system credential stores, session databases, or complete environment-variable dumps.

API credentials remain opaque and host-managed. The workflow may record a provider and whether authentication was available; it must never print, copy, serialize, hash, persist, or place a credential in a prompt, command argument, URL, Git remote, log, screenshot, state record, Cockpit, error report, compatibility artifact, or release archive. Local research content is private unless the user approves a specific disclosure. A research approval or recommended Skill cannot weaken these rules.

The repository allowlist is empty by default. A future suppression is eligible only for a `privacy.*` false positive and must bind an exact repository-relative path and SHA-256 line digest with a non-empty reason, human approval record, and unexpired ISO date. Credential, account, session, private-key, and credential-file findings are never suppressible.

## Reporting a Vulnerability

Use **GitHub Private Vulnerability Reporting** for this repository when it is enabled. If that private channel is unavailable, do not open a public report containing sensitive details; wait for a private repository reporting channel to be provided.

Never paste secrets, tokens, authorization headers, account or session data, private research content, personal paths, machine identifiers, or sensitive reproduction output into public issues, discussions, logs, screenshots, or reproduction repositories. A report can initially contain a concise impact description, affected public version or commit, and sanitized reproduction steps without the sensitive value itself.

## Incident Response

If a real credential or session value is exposed, stop publication and remove the material from the working revision. The affected owner must rotate the credential or revoke the session; deletion alone is not remediation once material may have been disclosed.

If sensitive content entered Git history, history cleanup and any force update require separate explicit authorization. After cleanup, the worktree, reachable history, author identities, and exact release archive must all be scanned again before any push, pull request, tag, release, marketplace publication, or public demo upload.

## Security Claims

Public statements may name a dated check, its version, scope, result, and limitation. They must not claim absolute security, zero risk, or protection beyond the evidence actually produced. A passing deterministic test is not a substitute for reachable-history, release-archive, independent scanner, client-runtime, or deployment evidence.
