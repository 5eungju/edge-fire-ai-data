import io
import unittest
import zipfile
from raw_recovery_reader import RawArchive, RecoveredZipReader


class FakeVolume:
    cluster_size = 512
    heap = 0
    cluster_count = 20
    def __init__(self, data): self.data=data; self.fat=[0]*22
    def read(self, offset, length): return self.data[offset:offset+length]


class RecoveryTests(unittest.TestCase):
    def test_fragmented_reads_cross_clusters_and_seek(self):
        volume=FakeVolume(b'a'*512+b'c'*512+b'b'*512)
        volume.fat[2]=4;volume.fat[4]=3;volume.fat[3]=0xffffffff
        stream=RawArchive(volume,{'cluster':2,'bytes':1536,'flags':1})
        self.assertEqual(stream.read(),b'a'*512+b'b'*512+b'c'*512)
        stream.seek(500)
        self.assertEqual(stream.read(40),b'a'*12+b'b'*28)
        volume.fat[4]=2
        with self.assertRaises(OSError):RawArchive(volume,{'cluster':2,'bytes':1536,'flags':1})

    def test_zip_directory_and_crc_on_recovered_extent(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('image.bin',b'example'*1000)
        payload=buffer.getvalue()
        reader=RecoveredZipReader(FakeVolume(payload),[{'cluster':2,'bytes':len(payload),'flags':3}])
        entries=list(reader.entries())
        self.assertEqual(reader.read(entries[0]),b'example'*1000)
        entries[0].crc^=1
        with self.assertRaises(ValueError):reader.read(entries[0])
        reader.close()


if __name__=='__main__': unittest.main()
