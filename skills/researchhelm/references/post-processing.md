# Post-processing

Transform verified experiment artifacts into auditable analysis without rewriting the registered history. Keep scientific interpretation separate from publication authority.

Use the artifact and claim fields defined in `schemas.md`. Apply `privacy-security.md` before creating any shareable export.

## Freeze Raw Results

Before analysis, freeze the manifest for code, configuration, data identifiers, environment, commands, logs, raw results, and hashes. Preserve failed and negative runs that belong to the registered experiment.

Never replace a raw artifact in place. Create a new derived artifact and record its inputs, transformation, version, and output hash.

## Analysis

Require every analysis to be derived from registered artifacts. Report effect sizes and uncertainty, not only point estimates.

Require every table and figure to be generated from registered artifacts. For each derived artifact, record its inputs, transformation, version, and output hash; never type values manually into a publication artifact.

Include the preregistered primary and secondary metrics, ablations, sensitivity analysis, resource use, and invariant checks. Discuss alternative explanations, failures, and negative results.

Label exploratory analyses as exploratory. Do not promote an exploratory metric or subgroup to a preregistered result after seeing the data.

When evidence is incomplete or unstable, narrow the claim instead of filling gaps with rhetoric.

## Claim-Evidence Matrix

Create one matrix row per material claim using the canonical fields in `schemas.md`. Link each claim to its registered artifacts, analysis, limitations, and responsible human decision.

Assign the claim status exactly as `supported|qualified|unsupported`. Use qualified when evidence supports only a narrower statement. Use unsupported when registered evidence does not substantiate the claim, even if the result is suggestive.

Make contradictions, missing artifacts, and unresolved audit findings visible. Do not omit them from a sanitized summary.

Publication, submission, public release, and external sharing are human-only publication decisions. Prepare a sanitized export only after the user approves its audience and data boundary; never publish autonomously.
