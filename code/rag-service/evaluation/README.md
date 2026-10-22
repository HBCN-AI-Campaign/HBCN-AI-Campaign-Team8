# Retrieval evaluation data

This directory intentionally contains no real cases or gold labels. Do not place customer documents, case text, law excerpts, credentials, or personal identifiers here. Use approved access-controlled storage for reviewed sets; use opaque case IDs and stable, non-reversible leakage-group IDs issued by the authorized curator.

The accepted JSON contract is implemented in `app/evaluation.py`. Each individual item must have an authorized reviewer, source snapshot, answerability, expected handling, graded evidence IDs pinned to the source snapshot, and curator-reviewed exact/general/translated query variants. A `holdout` set is rejected unless every one of the six planning groups has at least 20 individually reviewed cases. This enforces representation; it does not authenticate the curator or protect files on disk. Access control, signing, retention and read audit belong in the approved evaluation-data environment before real labels are stored.

Before metric disclosure, call `validate_split_isolation(development, holdout)` to reject overlapping case IDs or leakage groups. Leakage-group IDs must be generated in the controlled curation environment; do not derive them as unsalted hashes of customer identifiers.

Use `scripts/run-retrieval-evaluation.py` to collect rankings from the configured PostgreSQL/pgvector engine, then compare baseline RRF and the configured dedicated reranker over one shared candidate set. Query variants are frozen, reviewed inputs; no answer generation or query-planning LLM is called. Both runs share one collection pass and candidate-set hash. The lower-level `scripts/evaluate-retrieval-quality.py` can recompute metrics from those files. Ranking files carry opaque candidate/evidence IDs but can reveal corpus membership; keep them in approved evaluation storage. The report includes Recall@20, nDCG@10, per-case paired deltas, leakage-group cluster bootstrap intervals and a SHA-256 digest. It excludes `no_answer` examples from ranking metrics. It does not evaluate answer correctness, citations, refusals, authorization, law applicability, or response latency/cost. Those require separately reviewed labels and tests; ranking metrics alone do not certify acceptance.

Run from `code/rag-service`:

This is a reranker experiment: the live collector preserves the same complete pool of at most 20 candidates in both rankings, so Recall@20 cannot improve from reordering. Recall@20 describes candidate coverage here; nDCG@10 measures ranking changes. Compare retrieval strategies in a separate experiment that permits different candidate sets before claiming recall gains. Unjudged evidence currently receives grade zero; curated relevance coverage must be reviewed before interpreting real scores.

Intervals use a deterministic, paired leakage-group percentile bootstrap with 2,000 draws. Whole groups are resampled and the statistic is the per-question mean difference; this accounts for multiple questions from one case. Fewer than two independent groups produces no interval, and two groups are only enough to exercise the calculation, not evidence of a reliable quality estimate. The code does not implement BCa or a power/sample-size analysis. The paired-resampling principle is described in the [SciPy bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html); the group-level adaptation here is implemented in this project, without a SciPy dependency.

```powershell
python scripts/evaluate-retrieval-quality.py `
  --cases <approved-set.json> `
  --development <approved-development-set.json> `
  --baseline <rrf-run.json> `
  --candidate <ranker-run.json> `
  --output <new-report.json>
```

For live collection, use `python scripts/run-retrieval-evaluation.py` with `--baseline-output`, `--candidate-output`, and `--report-output`. For holdout sets, `--development` and case/leakage-group isolation are checked before retrieval. Default `--max-cases 120` bounds embedding and reranker work. Remote embedding and reranker endpoints require separate dataflow flags. Pkulaw cases additionally require `--allow-external-sources` and `--max-external-calls`; the latter counts source queries, each of which can call one search tool and up to two article tools. Partial external results abort. These flags acknowledge configured data flows; they are not legal approval. Output files are created exclusively in existing parent directories; ranking IDs can reveal corpus membership and must stay in the approved evaluation environment. The runner binds baseline/candidate to one invocation and candidate-set hash, but cannot attest that the index is immutable or independently verify the labels' source snapshot.
