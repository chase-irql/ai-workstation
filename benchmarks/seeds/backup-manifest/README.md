# backup-manifest benchmark seed

Manifest paths use `/` separators on every operating system. A leading `./` is removed, but meaningful leading dots in names are retained.

Exclusion patterns name a complete file or directory path component. Matching is case-insensitive for cross-platform consistency. For example, `tmp` excludes `tmp/cache.bin` and `src/tmp/cache.bin`, but does not exclude `attempt.py`; `.cache` excludes files beneath any `.cache` directory.
