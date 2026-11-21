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
