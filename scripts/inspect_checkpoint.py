"""Inspect explicit checkpoint indices and headers, never tensor values."""
import argparse
import json
import math
import os
from pathlib import Path
import struct

MAX_HEADER = 64 * 1024 * 1024
SIZES = {'BOOL': 1, 'U8': 1, 'I8': 1, 'I16': 2, 'U16': 2, 'F16': 2,
         'BF16': 2, 'I32': 4, 'U32': 4, 'F32': 4, 'I64': 8, 'U64': 8,
         'F64': 8, 'F8_E4M3': 1, 'F8_E5M2': 1, 'F8_E8M0': 1}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def safe_root(path, excluded):
    root = Path(os.path.abspath(path))
    if any(part in excluded for part in root.parts):
        raise ValueError('Excluded path')
    # Reject symlinks before traversing into the next component.
    for parent in list(reversed(root.parents)) + [root]:
        if parent.is_symlink():
            raise ValueError('Symlinked root component')
    if not root.is_dir():
        raise ValueError('Checkpoint root is not a directory')
    return root


def member(root, name, excluded):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Invalid checkpoint member')
    path = Path(name)
    if path.is_absolute() or any(p in ('', '.', '..') or p in excluded for p in name.split('/')):
        raise ValueError('Unsafe checkpoint member')
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('Symlinked checkpoint member')
    if not cursor.is_file():
        raise ValueError('Checkpoint member is not a regular file')
    return cursor


def header(path):
    file_size = path.stat().st_size
    with path.open('rb') as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError('Truncated checkpoint prefix')
        size, = struct.unpack('<Q', raw)
        if not 0 < size <= MAX_HEADER or size + 8 > file_size:
            raise ValueError('Invalid checkpoint header size')
        value = json.loads(stream.read(size), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError('Invalid checkpoint header')
    value.pop('__metadata__', None)
    cursor = 0
    for name, item in sorted(value.items(), key=lambda pair: pair[1]['data_offsets'][0]):
        if not isinstance(item, dict):
            raise ValueError('Invalid tensor descriptor')
        shape, offsets = item['shape'], item['data_offsets']
        if (not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape)
                or not isinstance(offsets, list) or len(offsets) != 2
                or any(type(n) is not int for n in offsets)):
            raise ValueError('Invalid tensor dimensions')
        start, end = offsets
        if start != cursor or end < start or end + size + 8 > file_size:
            raise ValueError('Invalid tensor offsets')
        dtype_size = SIZES.get(item['dtype'])
        if dtype_size is not None and math.prod(shape) * dtype_size != end - start:
            raise ValueError('Tensor byte count mismatch')
        cursor = end
    if cursor + size + 8 != file_size:
        raise ValueError('Unexpected tensor payload length')
    return value, cursor


def candidate_reason(name):
    lower = name.lower()
    terms = ('embed', 'lm_head', 'output', 'vocab', 'token', 'hash', 'ngram',
             'patch', 'ple', 'proj', 'scale', 'zero_point', 'adapter')
    return [term for term in terms if term in lower]


def inspect(root_arg, indices, excluded, require_flat=False):
    root = safe_root(root_arg, excluded)
    if require_flat:
        for entry in root.iterdir():
            if entry.name in excluded:
                raise ValueError('Excluded member in flat checkpoint')
            if entry.is_symlink() or not entry.is_file():
                raise ValueError('Flat checkpoint contains a non-regular member')
    report = {'roles': {}, 'files': {}, 'sensitive_candidates': [],
              'classification': 'Requires adapter dependency tracing; names are only hints'}
    cache = {}
    referenced = {}
    for specification in indices:
        role, separator, index_name = specification.partition('=')
        if not separator or not role or role in report['roles']:
            raise ValueError('Use unique role=index specifications')
        index_path = member(root, index_name, excluded)
        if index_path.stat().st_size > MAX_HEADER:
            raise ValueError('Index too large')
        data = json.loads(index_path.read_bytes(), object_pairs_hook=unique_object)
        mapping = data['weight_map']
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError('Invalid weight map')
        total = 0
        for name, filename in mapping.items():
            if require_flat and len(Path(filename).parts) != 1:
                raise ValueError('Nested member in flat checkpoint index')
            path = member(root, filename, excluded)
            if filename not in cache:
                cache[filename], byte_count = header(path)
                report['files'][filename] = {'tensor_count': len(cache[filename]),
                                             'payload_bytes': byte_count}
            if name not in cache[filename]:
                raise ValueError('Indexed tensor is missing')
            descriptor = cache[filename][name]
            start, end = descriptor['data_offsets']
            total += end - start
            referenced.setdefault(filename, set()).add(name)
            reasons = candidate_reason(name)
            if reasons:
                report['sensitive_candidates'].append(
                    {'role': role, 'name': name, 'file': filename,
                     'dtype': descriptor['dtype'], 'shape': descriptor['shape'],
                     'reason_hints': reasons})
        report['roles'][role] = {'tensor_count': len(mapping), 'tensor_bytes': total}
    report['unindexed_tensors'] = {
        filename: sorted(set(items) - referenced.get(filename, set()))
        for filename, items in cache.items()
        if set(items) - referenced.get(filename, set())}
    report['unknown_dtypes'] = sorted({item['dtype'] for values in cache.values()
                                      for item in values.values() if item['dtype'] not in SIZES})
    if require_flat:
        stored = {entry.name for entry in root.iterdir() if entry.suffix == '.safetensors'}
        if report['unindexed_tensors'] or stored != set(cache):
            raise ValueError('Flat checkpoint contains unindexed parameters')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--index', action='append', required=True, help='role=relative-index-file')
    parser.add_argument('--exclude-part', action='append', default=[], help='Additional excluded directory name')
    parser.add_argument('--require-flat', action='store_true')
    args = parser.parse_args()
    try:
        result = inspect(args.root, args.index, {'bkp', *args.exclude_part}, args.require_flat)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, struct.error):
        parser.exit(1, 'Checkpoint inspection failed; check indices, file structure and exclusions.\n')
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
