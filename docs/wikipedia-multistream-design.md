# Multistream-aware Wikipedia extraction

`offline_rag.wikipedia_multistream` parallelizes safely around Wikimedia's multistream boundaries without changing the version-1 Wikipedia record contract. The sequential extractor remains available for compatibility and small fixtures.

## Index offsets and stream blocks

Each multistream index row contains a compressed-file byte offset, page ID, and title. Consecutive rows sharing an offset belong to one independently decompressible bzip2 stream block. The planner must group rows by offset and derive each block's compressed byte range from the next distinct offset; the final block ends at the archive size.

Workers should open the archive independently, seek to an assigned block offset, read only that block's byte range, and decompress it as a standalone bzip2 stream. A block is the smallest checkpoint and retry unit. Page IDs and titles from the index are planning metadata; XML remains authoritative.

## Deterministic sharding and parallelism

The planner writes an immutable run manifest containing archive identity, multistream-index identity, extraction configuration, and ordered block offsets. Adjacent blocks are grouped deterministically by a compressed-byte target with a hard block-count ceiling. Worker count changes scheduling but not part identity.

Each worker writes private Zstandard document and chunk JSONL shards. Workers never append to shared JSONL files. Temporary output is closed, flushed, fsynced, renamed, hashed, and then published through an atomic part manifest. A failed part is retried as a whole; its bounded input size limits retry cost.

## Ordering

Workers finish out of order, while part ordinals preserve canonical archive order. The corpus manifest lists parts by ordinal, and the indexer consumes that order directly. No uncompressed merge is required.

## Restart and duplicate prevention

A restart loads the immutable run manifest and validates archive, index, parser, and chunking identities. Completed part artifacts are accepted only when their recorded byte sizes and SHA-256 hashes match. `--quick-resume` intentionally reduces this to size validation. Missing, temporary, mismatched, or failed parts are reprocessed. Stable document and chunk IDs provide a second duplicate check during indexing.

Each part manifest records its block range, page/document/chunk counts, artifact names, hashes, and timing. The final corpus manifest contains aggregate counts and every accepted part in deterministic order. Extraction statistics include a conservative storage forecast calibrated from a distributed real-dump sample.

## Migration from sequential extraction

Version-1 sequential JSONL remains a supported input. The multistream extractor should emit the same Wikipedia fields or the corpus-neutral schema through the existing adapter. Migration should begin with a small set of blocks and compare normalized records, IDs, counts, redirects, headings, and retrieval results against the sequential extractor. Full adoption should require a complete deterministic comparison on a bounded dump subset before replacing the sequential baseline.
