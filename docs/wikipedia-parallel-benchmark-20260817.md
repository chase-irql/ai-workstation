# Wikipedia parallel pipeline verification — 2026-08-17

Hardware: Intel Core i7-14700KF, 64 GiB RAM, NVMe D:, eight extraction workers. GPU and local models were not used.

## Distributed real-dump sample

The sample selected 16 parts spread deterministically across `enwiki-20260801` using 16 blocks per part. The final partial part contained eight blocks.

- 248 multistream blocks and 24,750 indexed pages
- 18,585 main-namespace documents, including 11,440 redirects
- 48,869 searchable chunks
- 21,966,439 bytes of Zstandard shards
- 59.2 seconds extraction time after the one-time plan build
- 314 documents/second overall
- projected full shards: 22,848,639,534 bytes
- projected full chunk count: 50,831,642

The contentless SQLite build consumed the compressed shards directly, without a merge file:

- 18,585 documents and 48,869 chunks indexed
- 10.377 seconds build time
- 134,561,792-byte database
- 2,753.5 database bytes per chunk
- successful AND-mode query for `computer programming`, with document IDs, headings, source URLs, revision timestamps, and citations

The production forecast uses 3,000 SQLite bytes per chunk to retain a safety margin over the measured value.

## Opening-block stress sample

The first 128 blocks contained 12,702 documents and 183,743 chunks. They produced 101,893,811 compressed bytes and were far larger than the distributed sample, demonstrating that an alphabetic prefix is unsuitable for storage forecasting. A detached output pipe also caused progress logging to raise `OSError`; progress reporting was changed so console loss cannot fail extraction. All eight atomic part manifests remained resumable.

## Verification commands

```powershell
$env:PYTHONPATH = 'D:\ai-workstation\rag\src'
.\.venv\Scripts\python.exe -m pytest -q .\rag\tests
.\.venv\Scripts\python.exe -m compileall -q .\rag\src .\rag\tests
.\.venv\Scripts\python.exe -m offline_rag.bm25 build --input <distributed-sample> --database <temporary-database> --allow-incomplete
.\.venv\Scripts\python.exe -m offline_rag.bm25 query --database <temporary-database> --query 'computer programming' --limit 3 --mode and
```

Result: 33 tests and 3 subtests passed; Python compilation and PowerShell parser checks passed.
