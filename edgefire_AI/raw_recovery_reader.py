"""Read ZIPs through recovered exFAT extents, without modifying the source volume.

This is an explicit recovery mode, not a filesystem repair. Configuration and
state stay off the source volume. Source-volume shards need explicit allocation
guards in the caller. Member reads retain ZIP CRC checks.
"""
import array
import io
import json
import struct
from pathlib import Path
from split_zip_reader import ZipReader


class RawVolume:
    def __init__(self, config):
        self.config = config
        self.handle = open(config['device'], 'rb', buffering=0)
        boot = self.read(0, 512)
        if boot[3:11] != b'EXFAT   ' or struct.unpack_from('<I', boot, 100)[0] != config['volume_serial']:
            self.close()
            raise ValueError('Recovery source volume identity mismatch')
        self.sector = 1 << boot[108]
        self.cluster_size = self.sector * (1 << boot[109])
        self.heap = struct.unpack_from('<I', boot, 88)[0] * self.sector
        self.cluster_count = struct.unpack_from('<I', boot, 92)[0]
        offset = struct.unpack_from('<I', boot, 80)[0] * self.sector
        size = struct.unpack_from('<I', boot, 84)[0] * self.sector
        offset += (struct.unpack_from('<H', boot, 106)[0] & 1) * size
        self.fat = array.array('I', self.read(offset, size))

    def read(self, offset, length):
        if length == 0:
            return b''
        # Windows raw-volume reads must be sector aligned.
        start = offset // 512 * 512
        end = (offset + length + 511) // 512 * 512
        self.handle.seek(start)
        data = self.handle.read(end - start)
        if len(data) != end - start:
            raise OSError('Short raw-volume read')
        return data[offset-start:offset-start+length]

    def close(self):
        self.handle.close()

    def assert_source_allocated(self):
        """Check the live allocation bitmap before permitting opt-in source writes.

        The existing FOUND files can alias original extents. This check does not
        restore those originals or make deleting any recovered files safe.
        """
        import numpy as np
        boot = self.read(0, 512)
        if struct.unpack_from('<I', boot, 100)[0] != self.config['volume_serial']:
            raise OSError('Source identity changed during recovery')
        root = struct.unpack_from('<I', boot, 96)[0]
        active = struct.unpack_from('<H', boot, 106)[0] & 1
        bitmap = None
        seen = set()
        while 2 <= root < self.cluster_count+2 and root not in seen:
            seen.add(root)
            data = self.read(self.heap+(root-2)*self.cluster_size, self.cluster_size)
            for pos in range(0, len(data), 32):
                entry = data[pos:pos+32]
                if entry[0] == 0x81 and (entry[1]&1) == active:
                    bitmap = {'cluster':struct.unpack_from('<I',entry,20)[0],
                              'bytes':struct.unpack_from('<Q',entry,24)[0], 'flags':1}
                    break
            if bitmap is not None: break
            root = self.fat[root]
        if bitmap is None: raise OSError('Active source allocation bitmap unavailable')
        bits = np.unpackbits(np.frombuffer(RawArchive(self, bitmap).read(), dtype=np.uint8), bitorder='little')
        if len(bits) < self.cluster_count: raise OSError('Truncated allocation bitmap')
        if not hasattr(self, '_source_indexes'):
            indexes = []
            for entry in self.config['archives'].values():
                archive = RawArchive(self, entry)
                count = (archive.size+self.cluster_size-1)//self.cluster_size
                indexes.append(np.arange(entry['cluster']-2, entry['cluster']-2+count, dtype=np.int64)
                               if archive.mapping is None else np.frombuffer(archive.mapping,dtype=np.uint32).astype(np.int64)-2)
            self._source_indexes = np.concatenate(indexes)
            if len(np.unique(self._source_indexes)) != len(self._source_indexes):
                raise OSError('Original archive extents overlap each other')
        if np.any(bits[self._source_indexes] == 0):
            raise OSError('Original archive extents marked free; source-volume writes forbidden')
        return int(len(self._source_indexes))


class RawArchive(io.RawIOBase):
    def __init__(self, volume, entry):
        self.volume, self.entry = volume, entry
        self.position = 0
        self.size = entry['bytes']
        self.mapping = None
        if not entry['flags'] & 2:
            needed = (self.size + volume.cluster_size - 1) // volume.cluster_size
            self.mapping = array.array('I')
            c = entry['cluster']
            seen = set()
            for _ in range(needed):
                if not 2 <= c < volume.cluster_count + 2 or c in seen:
                    raise OSError('Invalid or truncated recovered FAT chain')
                seen.add(c)
                self.mapping.append(c)
                c = volume.fat[c]
        elif not 2 <= entry['cluster'] or entry['cluster'] + (self.size + volume.cluster_size-1)//volume.cluster_size > volume.cluster_count+2:
            raise OSError('Recovered contiguous extent is outside volume')

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2): raise ValueError('Invalid seek mode')
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if position < 0: raise ValueError('Negative seek')
        self.position = position
        return position

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def read(self, size=-1):
        size = max(0, self.size-self.position) if size < 0 else max(0, min(size, self.size-self.position))
        chunks = []
        cs = self.volume.cluster_size
        while size:
            index, within = divmod(self.position, cs)
            c = self.entry['cluster']+index if self.mapping is None else self.mapping[index]
            take = min(size, cs-within)
            while take < size and (within+take) % cs == 0 and take < 8*1024*1024:
                next_index = index+(within+take)//cs
                nc = self.entry['cluster']+next_index if self.mapping is None else (self.mapping[next_index] if next_index < len(self.mapping) else -1)
                if nc != c+(within+take)//cs: break
                take += min(cs, size-take)
            chunks.append(self.volume.read(self.volume.heap+(c-2)*cs+within, take))
            self.position += take
            size -= take
        return b''.join(chunks)


class RawPath:
    def __init__(self, volume, entry): self.volume, self.entry = volume, entry
    def open(self, mode='rb'):
        if mode != 'rb': raise ValueError('Recovery sources are read only')
        return io.BufferedReader(RawArchive(self.volume, self.entry), buffer_size=1024*1024)


class RecoveredZipReader(ZipReader):
    def __init__(self, volume, entries):
        self.parts = [RawPath(volume, e) for e in entries]
        self.path = self.parts[-1]
        self.sizes = [e['bytes'] for e in entries]
        self.handles = {}
        with self.path.open() as stream:
            stream.seek(-min(self.sizes[-1], 131072), 2)
            tail = stream.read()
        pos = tail.rfind(b'PK\x05\x06')
        if pos < 0: raise ValueError('Recovered ZIP end record missing')
        end = struct.unpack_from('<4s4H2LH', tail, pos)
        self.cd_disk, self.entries_count, self.cd_size, self.cd_offset = end[2], end[4], end[5], end[6]
        if pos >= 20 and tail[pos-20:pos-16] == b'PK\x06\x07':
            _, disk, offset, count = struct.unpack_from('<4sLQL', tail, pos-20)
            if count != len(self.parts): raise ValueError('Recovered ZIP part count mismatch')
            record = struct.unpack('<4sQ2H2L4Q', self.span(disk, offset, 56))
            if record[0] != b'PK\x06\x06': raise ValueError('Invalid recovered ZIP64 record')
            self.cd_disk, self.entries_count, self.cd_size, self.cd_offset = record[5], record[7], record[8], record[9]
        if self.cd_disk != len(self.parts)-1:
            raise ValueError('Recovered central directory spans volumes')


def open_recovered_readers(config_path, fingerprint, output):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if Path(output).resolve().drive.upper() == config['source_drive'].upper():
        raise ValueError('Recovery mode forbids outputs on source volume')
    volume = RawVolume(config)
    readers = {}
    try:
        for role, files in fingerprint.items():
            entries = []
            for file in files:
                name = Path(file['path']).name
                entry = config['archives'][name]
                if entry['bytes'] != file['bytes']:
                    raise ValueError('Recovered archive size differs from original inventory: '+name)
                entries.append(entry)
            readers[role] = RecoveredZipReader(volume, entries)
        # Read actual compressed content from each role before admitting this source.
        for reader in readers.values():
            for entry in reader.entries():
                if not entry.name.endswith('/'):
                    reader.read(entry)
                    break
        return readers, volume
    except BaseException:
        for reader in readers.values(): reader.close()
        volume.close()
        raise
