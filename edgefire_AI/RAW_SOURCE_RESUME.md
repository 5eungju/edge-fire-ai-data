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
path. Do not apply it to another volume. Keep the source volume unchanged: all
new output, SQLite state and logs must go to C:; the raw backend rejects output
on the source drive. Preserve the old E: shards using `--existing-shards`.

The 2026-11-21 resume starts from 392,000 committed images. The separate full CRC
run was stopped to avoid competing source reads after 120,212 checks: 120,199
passed and 13 failed. Whole-source validation was not completed. Resume output
is limited to 28 GiB with a 15 GiB free-space floor. Reaching either limit pauses
the export; it does not mean all source entries have been processed.

Existing spatial split review blocks remain in force. Exported shards still
require quality review and corrected site grouping before training admission.
