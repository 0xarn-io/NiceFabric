# Issues / audit log


<!-- INTEGRITY-MARKER -->
## Integrity

This audit log is integrity-tagged. The checksum below is the **SHA-256 of every byte of this file from
the top down to (and not including) the `<!-- INTEGRITY-MARKER -->` line above**. Verify or recompute with:

```sh
sed '/<!-- INTEGRITY-MARKER -->/,$d' .claude/issues.md | sha256sum
```

Claude recomputes this on every audit pass; if the printed hash differs from the tag below, the file was
edited outside the audit. The tag is publicly verifiable — it makes tampering **evident**, not
impossible; enforced write-protection would require repo branch-protection, not a checksum.

**SHA-256:** `2db44c7da2748d71af3cf31660e55436771f2cdc7ced651bd1f84a6027196244`

_Owned & maintained by Claude (audit author) · read-only for everyone else · report-only._
