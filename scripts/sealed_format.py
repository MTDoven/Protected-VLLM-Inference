"""Trusted OFFLINE format reference. Never import into a serving decrypt path.

Python cannot promise secret-buffer erasure. These helpers are for provisioning
and synthetic tests only. The online loader must verify and decrypt on device.
"""
import hashlib
import json
import math
import secrets
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_N = 32768
KDF_R = 8
KDF_P = 1
KDF_MAXMEM = 64 * 1024 * 1024
MODEL_DOMAIN = b'model-unlock-v1\0'


def nonce(ordinal, chunk_index):
    if type(ordinal) is not int or not 0 < ordinal < 2**64:
        raise ValueError('Invalid tensor ordinal')
    if type(chunk_index) is not int or not 0 <= chunk_index < 2**32:
        raise ValueError('Invalid chunk index')
    return struct.pack('>QI', ordinal, chunk_index)


def aad(package, role, name, dtype, shape, chunk_index):
    if any(not isinstance(s, str) or not s for s in (package, role, name, dtype)):
        raise ValueError('Invalid tensor identity')
    if not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape):
        raise ValueError('Invalid tensor shape')
    if type(chunk_index) is not int or not 0 <= chunk_index < 2**32:
        raise ValueError('Invalid chunk index')
    return json.dumps([package, role, name, dtype, shape, chunk_index],
                      separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def aligned_chunk_bytes(row_bytes, target=8 * 1024 * 1024):
    if type(row_bytes) is not int or row_bytes < 1 or type(target) is not int or target < 16:
        raise ValueError('Invalid chunk dimensions')
    alignment = math.lcm(16, row_bytes)
    result = target // alignment * alignment
    if not result or result // 16 > 2**32 - 2:
        raise ValueError('Chunk cannot satisfy alignment and counter bounds')
    return result


def counter_location(byte_offset, chunk_bytes):
    if type(byte_offset) is not int or byte_offset < 0:
        raise ValueError('Invalid byte offset')
    if (type(chunk_bytes) is not int or chunk_bytes < 16 or chunk_bytes % 16
            or chunk_bytes // 16 > 2**32 - 2):
        raise ValueError('Invalid chunk size')
    chunk, within = divmod(byte_offset, chunk_bytes)
    if chunk >= 2**32:
        raise ValueError('Chunk identity overflow')
    block, inside = divmod(within, 16)
    return chunk, block + 2, inside


def _key(key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError('A 256-bit key is required')


def seal_chunk(key, plaintext, package, role, name, record, chunk_index):
    _key(key)
    result = AESGCM(key).encrypt(
        nonce(record['ordinal'], chunk_index), plaintext,
        aad(package, role, name, record['dtype'], record['shape'], chunk_index))
    return result[:-16], result[-16:].hex()


def open_chunk(key, ciphertext, tag, package, role, name, record, chunk_index):
    _key(key)
    if not isinstance(tag, str) or len(tag) != 32:
        raise ValueError('Invalid authentication tag')
    raw_tag = bytes.fromhex(tag)
    if len(raw_tag) != 16:
        raise ValueError('Invalid authentication tag')
    return AESGCM(key).decrypt(
        nonce(record['ordinal'], chunk_index), ciphertext + raw_tag,
        aad(package, role, name, record['dtype'], record['shape'], chunk_index))


def model_unlock_key(password, salt):
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError('Password must contain at least 6 characters')
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError('Invalid model salt')
    return hashlib.scrypt(password.encode('utf-8'), salt=salt + MODEL_DOMAIN,
                          n=KDF_N, r=KDF_R, p=KDF_P, dklen=32, maxmem=KDF_MAXMEM)


def wrap_key(password, data_key, package):
    _key(data_key)
    if not isinstance(package, str) or not package:
        raise ValueError('Invalid package identity')
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    encrypted = AESGCM(model_unlock_key(password, salt)).encrypt(
        iv, data_key, package.encode('utf-8'))
    return {'kdf': {'name': 'scrypt', 'n': KDF_N, 'r': KDF_R, 'p': KDF_P,
                    'salt': salt.hex()},
            'key_nonce': iv.hex(), 'wrapped_key': encrypted.hex()}


def unwrap_key(password, metadata, package):
    kdf = metadata['kdf']
    if (kdf['name'], kdf['n'], kdf['r'], kdf['p']) != ('scrypt', KDF_N, KDF_R, KDF_P):
        raise ValueError('Unsupported key derivation')
    iv, wrapped = bytes.fromhex(metadata['key_nonce']), bytes.fromhex(metadata['wrapped_key'])
    if len(iv) != 12 or len(wrapped) != 48:
        raise ValueError('Invalid wrapped key metadata')
    result = AESGCM(model_unlock_key(password, bytes.fromhex(kdf['salt']))).decrypt(
        iv, wrapped, package.encode('utf-8'))
    _key(result)
    return result
