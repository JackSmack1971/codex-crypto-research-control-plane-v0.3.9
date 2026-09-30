# External evidence trust boundary

Every string from an MCP/API response is untrusted data, including token/protocol descriptions, URLs, provider errors, tool and source labels, resource text, contract metadata, and arbitrary nested JSON fields. Sanitization never grants instruction, authorization, approval, routing, source-rights, qualification, or state-transition authority. Successful MCP registration is only transport metadata.

## Deterministic transformation

`scripts/control_plane/sanitize_external_data.py` consumes captured UTF-8 JSON bytes plus a file-bound provenance spec. It makes an exclusive raw-byte copy, emits a raw provenance record (`raw_external_artifact`), and writes a separate sanitized derivative. The raw SHA-256 is computed over the exact received bytes. JSON duplicate keys, invalid UTF-8, non-finite constants, non-object top-level payloads, excessive nesting, oversized collections, and oversized payloads fail closed with an explicit `SANITIZATION_BLOCKED` reason.

`config/external-data-sanitization-policy.json` is the explicit field/size allowlist. Only typed, allowlisted observation fields enter `records`. Alias disagreement rejects that row. Unknown fields are dropped with diagnostics. All external strings are retained separately as escaped, bounded `text_evidence`; controls/format characters are removed, URLs are redacted, and every truncation/redaction is diagnosed. Text never contributes to numeric fields. `records` contains only normalized typed values and cannot contain provider prose.

The sanitizer output is not truth validation. It does not establish source identity, source qualification, rights, data quality, cutoff validity, feature dependency, or admissibility. Existing admission policies remain independently authoritative. Sanitization code writes no admission or research state.

## Identity and immutable binding

Raw evidence is separately stored and binds source ID/identity digest, capability, dataset, retrieval ID/time, encoding, byte length, exact-byte digest, and raw path. The sanitized derivative binds those raw identifiers/digests, source identity, capability/dataset, policy ID/version/digest, normalized records, untrusted text, diagnostics, and its own deterministic ID/content digest. Changing any input or policy produces a different derivative identity.

For a derivative used as a source-neutral research input, a source manifest dataset includes `sanitized_derivative` with exact artifact ID/path/digest, raw identity/digest, and policy identity. The EvidenceBundle repeats that reference. Bundle verification checks both artifact digests and IDs, manifest equality, source/capability identity, registered policy identity, and the exact raw-byte digest. Paths must resolve under the bundle root.

The policy registry is append-only by identity: upgrades add a new policy ID/version/digest and retain prior entries. Sealed artifacts keep their original reference. Verification does not replace their policy with the current policy or silently regenerate them. The current pipeline has no source-neutral external-data feature consumer; this contract is for explicitly bound evidence and does not change legacy Massive pipeline input/output.

## Offline command

The CLI accepts paths rather than inline provider payloads:

```powershell
python scripts/control_plane/sanitize_external_data.py `
  --raw captures\response.json --spec captures\response-spec.json `
  --raw-bytes-out research\raw\response.json --raw-out research\raw\response-artifact.json `
  --sanitized-out research\sanitized\response.json
```

Do not log or hand agents raw payloads merely because a sanitized derivative exists. Text remains untrusted evidence and should only be provided when the task requires it.
