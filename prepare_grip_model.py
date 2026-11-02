"""Download a pinned, safetensors-only CLIP checkpoint for local grip images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

MODEL_ID = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
REVISION = '1a25a446712ba5ee05982a381eed697ef9b435cf'
MODEL_DIR = Path(__file__).resolve().parent / '.models' / 'grip-clip'
FILES = ('config.json', 'model.safetensors', 'preprocessor_config.json', 'merges.txt',
         'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json', 'vocab.json')


def prepare(destination=MODEL_DIR):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{MODEL_ID}/revision/{REVISION}?blobs=true', timeout=30) as response:
        metadata = json.load(response)
    remote = {item['rfilename']: item for item in metadata['siblings']}
    for name in FILES:
        target = destination / name
        expected = remote[name].get('lfs', {}).get('sha256')
        if target.is_file() and (not expected or hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == expected):
            print(f'{name}: ready', flush=True)
            continue
        temporary = target.with_suffix(target.suffix + '.download')
        print(f'Downloading {name}…', flush=True)
        for attempt in range(5):
            offset = temporary.stat().st_size if temporary.exists() else 0
            request = urllib.request.Request(f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}',
                                             headers={'Range': f'bytes={offset}-'} if offset else {})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    append = offset and response.status == 206
                    with temporary.open('ab' if append else 'wb') as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                break
            except (OSError, TimeoutError):
                if attempt == 4:
                    raise
                print(f'{name}: connection interrupted, resuming download', flush=True)
        with temporary.open('rb') as downloaded:
            digest = hashlib.file_digest(downloaded, 'sha256').hexdigest()
        if expected and digest != expected:
            temporary.unlink(missing_ok=True)
            raise ValueError(f'Checksum mismatch: {name}')
        os.replace(temporary, target)
    (destination / 'grip-model.json').write_text(json.dumps({'id': MODEL_ID, 'revision': REVISION}) + '\n')
    print(f'Image model ready: {destination}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    prepare(args.destination)
