# Transcript search

Use Reports → Transcript search to find **your own completed speech jobs**. Every word must match a full token. No wildcard, substring, regex or FTS operator syntax is accepted. Arabic/Persian yeh/kaf, digits and zero-width non-joiners are normalized in the index without altering original text. This independent search does not inherit the report date/queue filters.

Admin/supervisor role, reports/audit menus, and current view/caller-detail/playback grants for every proven recording queue are checked for each returned candidate and again when opening full text. Cross-owner discovery is not supported. Unproven recording chains remain closed. Automatic recognition requires human review; production Persian accuracy is not established by these search tests.

An indexed, deadline-bounded read considers at most 50 candidates and returns at most 20 permitted excerpts. No hidden totals or pagination counts are exposed. Empty results do not establish absence; jobs may be unprocessed, unindexed, unauthorized or outside this bounded window.

SQLite FTS5 resides in the existing private AI store. Completion and text indexing commit atomically. The optional AI worker migrates at most one historical completed result per cycle, with a durable cursor. HTTP performs no indexing, decoding, AMI or PBX SQL. Records/audio are not automatically deleted; monitor private-store and WAL growth. SQLite must provide FTS5; missing support closes search without breaking speech jobs or falling back to a full-table text scan.

API: `GET /api/history/transcripts/search?q=...`; limits: 256 characters, 12 literal tokens, 64 characters per token. Excerpts render with text nodes, never trusted HTML. Tests exercise actual FTS normalization, operator escaping, owner/PBX isolation, legacy migration, atomic failure and permission revocation across a multi-queue recording chain.
