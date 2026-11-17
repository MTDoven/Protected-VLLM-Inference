"""CPU wire primitives. Integrators supply TLS, authentication flow and policy."""
import asyncio
from collections import deque
import hashlib
import hmac
import json
import math
import struct
import time

VERSION = 3
PROFILE_VERSION = 1
RATE = 5_000_000
CHUNK = 60_000
MAX_MESSAGE = 128 * 1024 * 1024
MAX_HEADER = 1024 * 1024


def derive(password, salt):
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError('Password must contain at least 6 characters')
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError('Invalid authentication salt')
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768,
                          r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def proof(key, nonce, profile, image_transport):
    if len(key)!=32 or len(nonce)!=32 or len(profile)!=64:raise ValueError('Invalid authentication parameters')
    context=json.dumps(image_transport,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
    return hmac.new(key,b'private-v3\0'+nonce+profile.encode('ascii')+hashlib.sha256(context).digest(),hashlib.sha256).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Non-finite JSON value')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Non-finite JSON value')
    return number


def pack(meta, blobs=()):
    if not isinstance(meta, dict) or 'blob_lengths' in meta:
        raise ValueError('Invalid metadata')
    blobs = tuple(blobs)
    if any(not isinstance(blob, bytes) for blob in blobs):
        raise ValueError('Blobs must be bytes')
    header = json.dumps(dict(meta, blob_lengths=[len(b) for b in blobs]),
                        separators=(',', ':'), allow_nan=False).encode('utf-8')
    total = 4 + len(header) + sum(map(len, blobs))
    if len(header) > MAX_HEADER or total > MAX_MESSAGE:
        raise ValueError('Message too large')
    return struct.pack('<I', len(header)) + header + b''.join(blobs)


def unpack(data):
    if not isinstance(data, bytes) or not 4 <= len(data) <= MAX_MESSAGE:
        raise ValueError('Invalid message size')
    size, = struct.unpack_from('<I', data)
    if size > MAX_HEADER or 4 + size > len(data):
        raise ValueError('Invalid header')
    meta = json.loads(data[4:4 + size], object_pairs_hook=_object,
                      parse_constant=_constant, parse_float=_float)
    if not isinstance(meta, dict):
        raise ValueError('Invalid metadata')
    lengths = meta.pop('blob_lengths', None)
    if (not isinstance(lengths, list) or
            any(type(n) is not int or n < 0 for n in lengths) or
            sum(lengths) + size + 4 != len(data)):
        raise ValueError('Invalid blob lengths')
    position = size + 4
    blobs = []
    for length in lengths:
        blobs.append(data[position:position + length])
        position += length
    return meta, blobs


class WindowLimiter:
    """Share one instance across connections for each aggregate direction."""
    def __init__(self, rate=RATE):
        if type(rate) is not int or rate < 2:
            raise ValueError('Invalid rate')
        self.rate = rate
        self.events = deque()
        self.used = 0
        self.lock = asyncio.Lock()

    async def acquire(self, size):
        if type(size) is not int or not 0 < size <= self.rate:
            raise ValueError('Invalid window charge')
        async with self.lock:
            while True:
                now = time.monotonic()
                while self.events and self.events[0][0] <= now - 1:
                    self.used -= self.events.popleft()[1]
                if self.used + size <= self.rate:
                    self.events.append((now, size))
                    self.used += size
                    return
                await asyncio.sleep(max(0.0001, self.events[0][0] + 1 - now))


class Channel:
    """Framing and scheduling; not a network-interface traffic shaper."""
    def __init__(self, ws, upload=None, download=None):
        self.ws = ws
        self.tx = upload if upload is not None else WindowLimiter()
        self.rx = download if download is not None else WindowLimiter()
        self.send_lock = asyncio.Lock()
        self.recv_lock = asyncio.Lock()

    async def send(self, meta, blobs=()):
        data = pack(meta, blobs)
        chunk = min(CHUNK, self.tx.rate - 1)
        async with self.send_lock:
            for offset in range(0, len(data), chunk):
                final = int(offset + chunk >= len(data))
                piece = bytes([final]) + data[offset:offset + chunk]
                await self.tx.acquire(len(piece))
                await self.ws.send(piece)

    async def recv(self):
        async with self.recv_lock:
            parts = []
            total = 0
            while True:
                piece = await self.ws.recv()
                if (not isinstance(piece, bytes) or not 1 < len(piece) <= CHUNK + 1
                        or piece[0] not in (0, 1)):
                    raise ValueError('Invalid binary chunk')
                await self.rx.acquire(len(piece))
                total += len(piece) - 1
                if total > MAX_MESSAGE:
                    raise ValueError('Message too large')
                parts.append(piece[1:])
                if piece[0]:
                    return unpack(b''.join(parts))
