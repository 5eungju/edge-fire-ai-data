"""ZIP/ZIP64 분할 압축을 병합·전체 해제 없이 읽습니다. 원본은 읽기 전용입니다."""
from dataclasses import dataclass
from pathlib import Path
import struct,zlib

@dataclass
class Entry:
 name:str
 disk:int
 offset:int
 compressed:int
 uncompressed:int
 method:int
 crc:int
 flags:int

class ZipReader:
 def __init__(self,path):
  self.path=Path(path);self.parts=[]
  for i in range(1,100):
   part=self.path.with_suffix(f'.z{i:02d}')
   if not part.exists():break
   self.parts.append(part)
  self.parts.append(self.path);self.sizes=[p.stat().st_size for p in self.parts];self.handles={}
  if not self.sizes[-1]:raise ValueError(f'Empty archive: {self.path}')
  with self.path.open('rb') as f:
   f.seek(-min(self.sizes[-1],131072),2);tail=f.read()
  pos=tail.rfind(b'PK\x05\x06')
  if pos<0:raise ValueError('ZIP end record missing')
  end=struct.unpack_from('<4s4H2LH',tail,pos)
  self.cd_disk=end[2];self.entries_count=end[4];self.cd_size=end[5];self.cd_offset=end[6]
  if pos>=20 and tail[pos-20:pos-16]==b'PK\x06\x07':
   _,disk,offset,count=struct.unpack_from('<4sLQL',tail,pos-20)
   if count!=len(self.parts):raise ValueError('Missing split archive part')
   record=struct.unpack('<4sQ2H2L4Q',self.span(disk,offset,56))
   if record[0]!=b'PK\x06\x06':raise ValueError('Invalid ZIP64 record')
   self.cd_disk=record[5];self.entries_count=record[7];self.cd_size=record[8];self.cd_offset=record[9]
  if self.cd_disk!=len(self.parts)-1:raise ValueError('Central directory across volumes is unsupported')
 def close(self):
  for f in self.handles.values():f.close()
  self.handles={}
 def span(self,disk,offset,n):
  result=bytearray()
  while n:
   while disk<len(self.parts) and offset>=self.sizes[disk]:offset-=self.sizes[disk];disk+=1
   if disk>=len(self.parts):raise ValueError('Read outside archive')
   if disk not in self.handles:self.handles[disk]=self.parts[disk].open('rb')
   f=self.handles[disk];f.seek(offset);chunk=f.read(min(n,self.sizes[disk]-offset))
   if not chunk:raise ValueError('Truncated archive')
   result.extend(chunk);n-=len(chunk);offset+=len(chunk)
  return bytes(result)
 def entries(self):
  # 별도 핸들로 목록과 멤버 읽기의 위치가 서로 간섭하지 않게 합니다.
  with self.path.open('rb') as f:
   f.seek(self.cd_offset);start=f.tell()
   for _ in range(self.entries_count):
    header=f.read(46)
    if len(header)!=46:raise ValueError('Truncated directory')
    h=struct.unpack('<4s6H3L5H2L',header)
    if h[0]!=b'PK\x01\x02':raise ValueError('Invalid directory entry')
    name=f.read(h[10]).decode('utf8' if h[3]&2048 else 'cp437');extra=f.read(h[11]);f.read(h[12])
    compressed,uncompressed,disk,offset=h[8],h[9],h[13],h[16];pos=0
    while pos+4<=len(extra):
     tag,size=struct.unpack_from('<HH',extra,pos);data=extra[pos+4:pos+4+size];pos+=4+size
     if tag==1:
      q=0
      if uncompressed==0xffffffff:uncompressed=struct.unpack_from('<Q',data,q)[0];q+=8
      if compressed==0xffffffff:compressed=struct.unpack_from('<Q',data,q)[0];q+=8
      if offset==0xffffffff:offset=struct.unpack_from('<Q',data,q)[0];q+=8
      if disk==0xffff:disk=struct.unpack_from('<L',data,q)[0]
    if disk>=len(self.parts) or offset>=self.sizes[disk]:raise ValueError('Invalid volume offset')
    yield Entry(name,disk,offset,compressed,uncompressed,h[4],h[7],h[3])
   if f.tell()-start!=self.cd_size:raise ValueError('Directory length mismatch')
 def read(self,entry,max_bytes=128*1024*1024):
  if entry.flags&1:raise ValueError('Encrypted member unsupported')
  if entry.compressed>max_bytes or entry.uncompressed>max_bytes:raise ValueError('Member exceeds memory limit')
  h=struct.unpack('<4s5H3L2H',self.span(entry.disk,entry.offset,30))
  if h[0]!=b'PK\x03\x04':raise ValueError('Invalid local member header')
  raw=self.span(entry.disk,entry.offset+30+h[-2]+h[-1],entry.compressed)
  if entry.method==8:
   decoder=zlib.decompressobj(-15);data=decoder.decompress(raw,max_bytes+1)
   if len(data)>max_bytes or decoder.unconsumed_tail or not decoder.eof:raise ValueError('Invalid or oversized deflate stream')
  elif entry.method==0:data=raw
  else:raise ValueError('Unsupported compression method')
  if len(data)!=entry.uncompressed or zlib.crc32(data)&0xffffffff!=entry.crc:raise ValueError('Member CRC/size mismatch')
  return data
