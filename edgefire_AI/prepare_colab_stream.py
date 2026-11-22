"""Prepare metadata-only bootstrap and a private Colab notebook on the laptop.

Run without --url first. Start the bridge and temporary tunnel, then run again
with --url to generate the private notebook. Never publish the output directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse
from zipfile import ZipFile, ZIP_DEFLATED

from export_full_portable import approve_index


def prepare(portable, output, url=None, parent=None):
    portable, output = Path(portable).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent
    approve_index(portable)
    credentials = output / 'credentials.json'
    if not credentials.exists():
        credentials.write_text(json.dumps({'token': secrets.token_urlsafe(48)}), encoding='utf8')
    package = output / 'bootstrap.zip'
    if url is None:
        if package.exists():
            raise ValueError('Bootstrap already exists; preserve it or choose a new output directory')
        names = ['train_full_stream.py', 'full_zip_dataset.py', 'training_policy.py', 'export_full_portable.py',
                 'colab_stream_client.py', 'generic_pretrained_manifest.json', 'reviewed_background_links_full_v1.json',
                 'reports/full_preparation_quality_20261122.json']
        with ZipFile(package, 'w', ZIP_DEFLATED, compresslevel=3) as archive:
            for name in ('full_dataset.sqlite', 'portable_manifest.json', 'pretrained/yolo26n-seg.pt'):
                archive.write(portable / name, name)
            for name in names:
                archive.write(source / name, 'code/' + name)
        print('Metadata-only bootstrap prepared:', package, flush=True)
        return
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.trycloudflare.com'):
        raise ValueError('Use the actual temporary HTTPS tunnel URL')
    if not package.exists():
        raise ValueError('Prepare bootstrap before starting the bridge')
    import requests
    token = json.loads(credentials.read_text('utf8'))['token']
    response = requests.get(url.rstrip('/') + '/manifest', headers={'Authorization': 'Bearer ' + token},
                            timeout=60, allow_redirects=False)
    response.raise_for_status()
    health = response.json()
    with package.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if health['package_sha256'] != digest:
        raise ValueError('Running bridge serves a different bootstrap')
    config = dict(url=url.rstrip('/'), token=token, dataset_identity=health['identity']['dataset_sha256'],
                  bootstrap_sha256=digest, preprocess=health['preprocess'])
    if parent:
        config['parent_remote_checkpoint'] = parent
    (output / 'connection.json').write_text(json.dumps(config, indent=2), encoding='utf8')
    notebook = json.loads((source / 'colab/EDGEFIRE_C_Stream_GPU.ipynb').read_text('utf8'))
    marker = 'CONFIG=json.loads(Path("/content/edgefire_bridge_connection.json").read_text())'
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            text = ''.join(cell['source']).replace(marker, 'CONFIG=' + repr(config))
            cell['source'] = text.splitlines(keepends=True)
    target = output / 'EDGEFIRE_GPU_PRIVATE.ipynb'
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding='utf8')
    print('Private GPU notebook ready:', target, flush=True)
    print('Connection credentials remain in local output files; do not publish them.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--portable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url')
    parser.add_argument('--parent-remote-checkpoint')
    args = parser.parse_args()
    prepare(args.portable, args.output, args.url, args.parent_remote_checkpoint)
