# Resume from recovered source extents

The source filesystem paths are still unavailable. This mode reads the original
archive bytes directly from the exFAT volume using a separately saved recovery
map. It does not restore directory entries or repair the filesystem.

`preprocess_full_inventory.py --raw-recovery-map <C-drive-map.json>` checks the
source volume serial number, archive sizes against the original index, valid
cluster chains, ZIP/ZIP64 end records, and an actual member CRC from each role
before continuing. Every processed image and label also passes the existing ZIP
CRC, geometry, pixel decoding, metadata and duplicate checks. This is not a
claim that every original archive byte has been verified.

The map is local recovery metadata, not a dataset download or a portable file
path. Do not apply it to another volume. SQLite state and logs must remain on
C:. By default new output also stays off the source volume. Preserve old shards
using `--existing-shards`.

The 2026-11-21 resume starts from 392,000 committed images. The separate full CRC
run was stopped to avoid competing source reads after 120,212 checks: 120,199
passed and 13 failed. Whole-source validation was not completed. Resume output
is limited to 28 GiB with a 15 GiB free-space floor. Reaching either limit pauses
the export; it does not mean all source entries have been processed.

## Opt-in E: shard destination after C: space pause

The first resumed run stopped safely at 444,315 accepted images, with 52,315
new images committed to C:. A read-only raw directory walk checked 37,444 active
entries across 159 directories. The original archives do not overlap each other.
Some FOUND.001 files alias original source clusters: never delete these files.
All 5,433,218 original archive clusters were marked allocated in the live bitmap.
Filesystem metadata snapshots were saved to C:, not a full source-data backup.

The user requested E: storage because C: was full. An explicit
`--allow-recovery-source-shards --shard-output E:/AI_Work/edgefire_full_export_recovered_v2/shards`
mode permits new ZIP shards only while every original cluster remains allocated.
This guard runs before creating the destination and before each new shard. State
remains in C:, the existing C: and E: shards are read-only inputs, and nothing is
moved or deleted. Filesystem paths for original archives remain unrestored.

The new shard budget is 80 GiB with 25 GiB reserved on the shard volume and a
separate 5 GiB floor on the C: state volume. These are protective limits, not a
promise that the remaining full export will fit. Unexpected allocation changes
or I/O failures stop the run. This does not provide a separate physical backup.

Existing spatial split review blocks remain in force. Exported shards still
require quality review and corrected site grouping before training admission.

The live full-quality auditor uses `--sqlite-cache-mib 512` after profiling
excessive repeated small SQLite index reads with the default page cache. This
setting changes memory caching only: CRC checks, label validation, perceptual
thresholds and candidate search limits are unchanged. The uncapped reader has a
separate 64 MiB page cache. State remains in C: and comparisons resume from
committed shards after restart.

`audit_export_metadata.py` supplements the pixel/similarity audit by checking
every exported original annotation's declared dimensions against the actual
source dimensions recorded during decoding. It also checks camera IDs, output
size/aspect ratio and empty exported object lists, and indexes image IDs and
cameras for final candidate review. Run it with the same `--source`, both E:
`--extra-shards` directories, a C: `--output`, and `--follow`. Issues are recorded
for exclusion/review; annotations are never silently rewritten. Its full-export
completion flag must also be true before claiming the automated scans finished.

## Fresh export integrity check after the earlier filesystem incident

The annotation scan found a damaged local ZIP header in an older E: export that
had already been audited before filesystem recovery. Its size and timestamp had
not changed. Those attributes alone do not prove content survived a repair.
Fresh allocation checks found no active file/directory overlaps or free-marked
active extents, and all source archive clusters remained allocated. The exact
time/cause of the derived-byte damage is not established.

`revalidate_export_integrity.py` checks every finalized export member's CRC,
compares image SHA-256 against existing quality sketches where present, and
records a fresh whole-shard SHA-256. A damaged derived image is reconstructed
from its original archive only after original CRC and raw SHA checks. Every
reconstructed member must match the old export CRC and every cached image SHA
must match, with the committed manifest unchanged. Replacements are built and
fully checked on C:. Damaged exports are retained with a `.corrupt-preserved-20261122`
suffix; no original archive is renamed or deleted. A successful byte-identical
repair updates only the affected cache fingerprint; the old sketches remain
valid. All producers and auditors must be stopped while repairing.

The first repaired shard contained four damaged members affecting two images;
both were recovered with matching original quality SHA values. A complete
fresh integrity sweep is required before resuming the paused pipeline. For a
later, separate filesystem incident use a fresh output directory or
`--force-recheck`: prior size/mtime checkpoints must not be treated as new proof.

Before resuming, new export finalization also flushes each closed partial ZIP
with `fsync` before renaming it and committing accepted IDs on C:. A delayed
write error therefore leaves an unadmitted partial instead of a committed shard.
This improves write-error detection; it is not a physical backup or a promise
against all device failures.

The uncapped recheck now slices the ascending row-ID snapshot at each image's
last completed checkpoint before filtering colors and computing Hamming
distances. Earlier pairs are not recomputed on every follow pass. Scalar
exhaustive-search equivalence tests, including gaps and late checkpoints, confirm
the same candidate results without adding a search cap.

The pixel auditor now uses a scalar covering index for candidate filtering and
fetches RGB sketches only for candidates within the Hamming threshold. An
80-image read-only production-snapshot comparison returned exactly the same
selected IDs, cap flags and MSE values; the isolated candidate-query portion was
4.36 times faster in that run. This is a query microbenchmark, not an end-to-end
completion-time guarantee. Split/color filters, search caps and MSE thresholds
are unchanged; capped cases still require the separate uncapped pass.

`review_full_quality.py` runs only after preprocessing, pixel/similarity checks,
the uncapped pass, metadata checks, and the final whole-export integrity sweep
finish. It verifies ID, source SHA, site and fold coverage across their databases.
Every flagged camera relation must be covered by explicit visual review.

For a reviewed component spanning old folds, the admission mask retains its
existing train rows before existing val rows before existing test rows. Other
folds in that component are quarantined, never reassigned. All retained folds
therefore remain subsets of the audited original folds: this cannot create new
cross-fold pairs that the existing audit did not inspect. Metadata issues also
produce exclusions. The report includes retained class coverage and verifies
that no known cross-fold candidate pair remains wholly admitted.

The images and old manifests are preserved. A later training loader must honor
the new admission mask and an approved dataset identity; this report does not
unblock V4, certify geographic independence, train a model or promote weights.
