# Homepage Subject Catalogue

`material-subject-catalogue.json` contains a reviewed snapshot of public material
card metadata and subject assignments. Only the homepage subject view uses it.
Opening folders does not query APIs or classify the database at runtime.

Refresh periodically, or after a publication/removal:

```bash
cd frontend
node scripts/update-material-subjects.mjs
node scripts/update-material-subjects.mjs --write
npm run test:unit
```

The first command only checks the new catalogue. Review the generated diff before
committing and deploying it. Alias rules live in `constants/materialSubjects.ts`;
unrecognized titles remain under `其他资料` rather than being hidden.

The refresh script makes anonymous public GET requests only. It refuses partial,
duplicate or empty snapshots and replaces the local JSON atomically. It does not
modify database rows, files, permissions, or publication status. A refresh is not
part of page requests or builds. Cards reflect the snapshot date; details, payment,
download access and current availability still use the existing live checks.

No storage keys, download URLs, netdisk links/passwords, email addresses or private
user records are exported. Do not add these fields to the metadata allowlist.

Search also shows relevant subject folders alongside the live material results.
Folder names and course abbreviations use the existing public alias rules plus
the relevant course groups from `private/material_search_synonyms.json`. The
server reads and mtime-caches that private file; only aliases for public subjects
reach homepage props. Unrelated glossary entries are not serialized. Set
`STUDYHUB_MATERIAL_SEARCH_SYNONYMS_PATH` to override the shared path. Missing or
invalid files fall back to the public course aliases and do not break browsing.
Keep the full glossary and its backups out of Git. Folder search and opening a
folder do not make extra requests; opening shows the full curated subject within
the selected metadata/price filters. Returning keeps the original search results.

For a local preview against the running backend, set `NEXT_PUBLIC_API_BASE=/api`
and `API_BASE_INTERNAL=http://127.0.0.1:8311/api` for both build and start. Use a
separate `NEXT_DIST_DIR` and port. Without the public setting, loopback browser
requests use the development backend on port 8111, which may not be running.
