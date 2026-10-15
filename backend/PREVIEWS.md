# Deferred Material Previews

Uploads only persist a pending manifest. They never render a PDF, wait for an
image conversion, or start an unbounded in-process background task. A failed
preview does not undo an accepted submission or change download permissions.

`python -m app.ops.material_previews --limit 2` processes at most two documents.
The systemd timer waits a minute between runs, uses one worker, low CPU/IO
priority and a 512 MiB cgroup limit. The credential-free rendering subprocess
has a 384 MiB address-space limit, 30 CPU seconds and a 40-second wall timeout.
Linux requires `libseccomp.so.2`; the child denies network sockets and does not
initialize PDF forms/JavaScript. These limits reduce risk but do not make native
PDF parsing a complete security sandbox. Keep PDFium/Pillow patched.

PDF previews contain the first three real pages (or fewer for short files),
at most 1200 x 1800 pixels, encoded as WebP. Manual preview images use the same
watermark pipeline. Watermarks say **StudyHub**, not a deployment hostname.
Disabling the existing watermark option remains supported. Source bytes are
never changed. Experience-post illustrations remain ordinary illustrations.
Rendering only checks the PDF structure/encryption and uses a PDFium build
without V8/XFA. It does not reuse the malware scanner's object-count heuristic,
which can reject large benign legacy PDFs. The upload/download malware policy
and CLEAN gate remain unchanged. A failed upgrade retains a matching last-good
preview; changed source files or watermark policy cannot reuse stale previews.

The existing `materials.preview_manifest` stores generation state and page
metadata; no schema migration is needed. Readers support historical real
images while upgrading. Placeholders and invented page counts are not used.
The worker compares the source, watermark and moderation snapshot before
publishing. Concurrent edits/deletion cannot publish stale results. Failed
jobs retry up to three times with an hour's backoff; killed jobs expire after
ten minutes. Changing source or watermark starts a fresh generation.
Abandoned temporary copies older than ten minutes are removed under the worker
lock; generation pauses below 256 MiB of free temporary disk space.

Preview asset tokens expire and are checked against the active manifest and
moderation/security state. Only preview copies are served. Database and storage
errors never silently turn into a successful placeholder response.

## Production Rollout

1. Back up the database with the existing encrypted backup command. Save the
   before/after aggregate audit privately. Do not print object keys or secrets.
2. Build an isolated backend release. If production lags behind main, apply
   only the reviewed preview diff to the deployed baseline, not unrelated main
   changes. Install the hash-locked dependencies in a separate virtualenv.
3. Run the preview tests and a production read-only API smoke before switching.
4. Generate a single historical preview; inspect the real image, counts and
   StudyHub watermark. Then enable `scripts/security/install-material-previews.sh`.
5. The timer regenerates historical `.store` derivatives from originals. It
   never rewrites original files, users, orders, earnings or publication status.
6. Retain old preview objects and the encrypted snapshot for rollback. This
   worker only removes its own uncommitted output after failed generation.
   Originals that already contain a baked-in watermark cannot be cleaned
   without an unwatermarked source; do not cover or erase document content.

Inspect `journalctl -u studyhub-material-preview.service` for aggregate counts.
After correcting a source or renderer problem, an operator can retry a specific
failed item with `python -m app.ops.material_previews --material-id ID --retry-failed`.
Roll back executable releases independently of data; the manifest format is
readable by older servers. Do not restore an entire production database just
to roll back preview metadata.
