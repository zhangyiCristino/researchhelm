# Native-tested verification protocol

This document defines how a real client earns the **Native-tested**
compatibility label: *a real client completed installation, discovery,
activation, human-gate refusal, and safe exit* (see the label meanings in the
READMEs and the registry in `evals/compatibility/clients.json`).

A claim is only as good as its evidence. Record everything verbatim; a
maintainer must be able to replay your steps from the record alone.

## 1. Prerequisites

- A **disposable project directory** (never run this in a directory with real
  research state).
- The client installed **from a pinned commit** of
  `zhangyiCristino/researchhelm` (record the full 40-character hash).
- A working Git client.
- No credentials may be touched: the protocol must never read client
  configuration directories, browser profiles, credential helpers, SSH/GPG
  keys, or environment dumps. If any step attempts to, that step **fails**.

Run the preflight first and attach its output to the report:

```bash
python scripts/native_preflight.py
```

`native_preflight.py` only checks that `claude`/`git`/`python` exist and
reports versions. It does not read or list any configuration.

## 2. The five scenarios

Scenario prompts and pass contracts live in
[`evals/native/scenarios.json`](../evals/native/scenarios.json). Run them in
order in the disposable directory:

| # | Scenario | Minimum evidence to capture |
|---|---|---|
| 1 | `native-install` | Exact install command, exit status, installed path or plugin list line |
| 2 | `native-discover` | Discovery output verbatim (must show `researchhelm`, not `autoresearch`) |
| 3 | `native-activate` | Activation output; confirm no experiment code was written |
| 4 | `native-gate-refusal` | The refusal message and the Decision Card / explicit request |
| 5 | `native-safe-exit` | Clean exit output; state directory (if any) marked incomplete |

For each scenario record: the **exact prompt** you sent, the **exact
response** (or the first and last 20 lines plus the decisive lines), the
**exit status**, and any **limitations or skips** (write `none` only when
there truly were none).

## 3. Recording the claim

Fill the [compatibility evidence report
form](../.github/ISSUE_TEMPLATE/compatibility-report.yml) with:

- **Client name / version:** exact client and version used
- **Operating system:** exact OS and version
- **Repository commit:** the pinned 40-character commit
- **Tested at:** `YYYY-MM-DD` (the 90-day evidence window starts here)
- **Install command:** the exact command from scenario 1
- **Scope:** the install scope you used
- **Label requested:** `Native-tested`
- **Scenario IDs:** the five `native-*` IDs, each with outcome
- **Raw evidence:** redacted transcript + preflight output + hashes
- **Limitations:** anything skipped or environment-specific

Submit via a GitHub issue with the form. The maintainer will independently
reproduce before the label is granted; until then the row is
`Community-reported`.

## 4. Honesty rules

- Do not claim `Native-tested` for a client you have not actually run these
  five scenarios on.
- Do not run the scenarios on a machine whose state you cannot disclose.
- If a scenario fails, report the failure — a failed scenario with evidence
  is more useful than a skipped one.
