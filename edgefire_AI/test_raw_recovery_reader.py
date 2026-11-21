import io
import struct
import unittest
import zipfile
from raw_recovery_reader import RawArchive, RecoveredZipReader, RawVolume


class FakeVolume:
    cluster_size = 512
    heap = 0
    cluster_count = 20
    def __init__(self, data): self.data=data; self.fat=[0]*22
    def read(self, offset, length): return self.data[offset:offset+length]


class RecoveryTests(unittest.TestCase):
    def test_source_writes_require_every_original_cluster_allocated(self):
        data=bytearray(4096)
        struct.pack_into('<I',data,96,2)
        struct.pack_into('<I',data,100,123)
        data[512]=0x81
        struct.pack_into('<I',data,512+20,3)
        struct.pack_into('<Q',data,512+24,3)
        data[1024:1027]=bytes([255,255,15])
        volume=RawVolume.__new__(RawVolume)
        volume.config={'volume_serial':123,'archives':{'sample.zip':{'cluster':4,'bytes':512,'flags':3}}}
        volume.cluster_size=512;volume.cluster_count=20;volume.heap=512
        volume.fat=[0]*22;volume.fat[2]=0xffffffff;volume.fat[3]=0xffffffff
        volume.read=lambda offset,length:bytes(data[offset:offset+length])
        self.assertEqual(volume.assert_source_allocated(),1)
        data[1024]&=~4
        with self.assertRaisesRegex(OSError,'marked free'):volume.assert_source_allocated()

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
