"""Synthetic CPU checks. No deployment files or live services are accessed."""
import asyncio
from collections import deque
import json
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'assets'))
import wire
import image_transport
import inspect_checkpoint as checkpoint
import sealed_format as sealed


class FormatChecks(unittest.TestCase):
    def test_published_zero_vectors(self):
        aes = AESGCM(bytes(32))
        self.assertEqual(aes.encrypt(bytes(12), b'', b'').hex(),
                         '530f8afbc74536b9a963b4f1c4cb738b')
        self.assertEqual(aes.encrypt(bytes(12), bytes(16), b'').hex(),
                         'cea7403d4d606b6e074ec5d3baf39d18d0d1c8a799996bf0265b98b5d48ab919')

    def test_chunk_binding_and_tampering(self):
        key = bytes(range(32))
        for ordinal, size in enumerate((0, 1, 15, 16, 17, 1024, 8193), 7):
            data = bytes(i % 251 for i in range(size))
            record = {'ordinal': ordinal, 'dtype': 'U8', 'shape': [size]}
            encrypted, tag = sealed.seal_chunk(key, data, 'fixture', 'target', 'test.weight', record, 3)
            self.assertEqual(sealed.open_chunk(key, encrypted, tag, 'fixture', 'target',
                                               'test.weight', record, 3), data)
            variants = [
                ('changed', 'target', 'test.weight', record, 3),
                ('fixture', 'draft', 'test.weight', record, 3),
                ('fixture', 'target', 'other.weight', record, 3),
                ('fixture', 'target', 'test.weight', dict(record, ordinal=ordinal + 100), 3),
                ('fixture', 'target', 'test.weight', dict(record, dtype='I8'), 3),
                ('fixture', 'target', 'test.weight', dict(record, shape=[size, 1]), 3),
                ('fixture', 'target', 'test.weight', record, 4),
            ]
            for identity in variants:
                with self.assertRaises(InvalidTag):
                    sealed.open_chunk(key, encrypted, tag, *identity)
            corrupt_tag = (bytes([int(tag[:2], 16) ^ 1]) + bytes.fromhex(tag[2:])).hex()
            with self.assertRaises(InvalidTag):
                sealed.open_chunk(key, encrypted, corrupt_tag, 'fixture', 'target', 'test.weight', record, 3)
            if data:
                corrupt = bytes([encrypted[0] ^ 1]) + encrypted[1:]
                with self.assertRaises(InvalidTag):
                    sealed.open_chunk(key, corrupt, tag, 'fixture', 'target', 'test.weight', record, 3)

    def test_nonce_and_random_access(self):
        nonces = {sealed.nonce(i, j) for i in range(1, 5) for j in range(5)}
        self.assertEqual(len(nonces), 20)
        self.assertEqual(sealed.nonce(1, 2), bytes(7) + b'\1' + bytes(3) + b'\2')
        for row_bytes in (3, 16, 37, 96):
            chunk = sealed.aligned_chunk_bytes(row_bytes, target=8192)
            self.assertEqual(chunk % row_bytes, 0)
            self.assertEqual(chunk % 16, 0)
            for offset in (0, 15, 16, chunk - 1, chunk, chunk + 17, 3 * chunk):
                index, counter, inside = sealed.counter_location(offset, chunk)
                self.assertEqual(index * chunk + (counter - 2) * 16 + inside, offset)
        for ordinal, index in ((0, 0), (2**64, 0), (1, -1), (1, 2**32)):
            with self.assertRaises(ValueError):
                sealed.nonce(ordinal, index)

    def test_separate_kdf_and_wrapping(self):
        password = 'Synthetic test password'
        salt = bytes(16)
        self.assertEqual(len(salt + sealed.MODEL_DOMAIN), 32)
        self.assertNotEqual(wire.derive(password, salt), sealed.model_unlock_key(password, salt))
        key = bytes(range(32))
        metadata = sealed.wrap_key(password, key, 'fixture')
        self.assertEqual(sealed.unwrap_key(password, metadata, 'fixture'), key)
        for attempt, package in (('Wrong test password', 'fixture'), (password, 'other')):
            with self.assertRaises(InvalidTag):
                sealed.unwrap_key(attempt, metadata, package)
        with self.assertRaises(ValueError):
            wire.derive('short', salt)
        nonce = bytes(32)
        auth_key = wire.derive(password, salt)
        transport=image_transport.negotiation(bytes(16),'minicpm',1)
        self.assertNotEqual(wire.proof(auth_key, nonce, 'a'*64,transport), wire.proof(auth_key, nonce, 'b'*64,transport))


class AlgebraChecks(unittest.TestCase):
    def test_token_rows_outputs_and_specials(self):
        random = np.random.default_rng(913)
        vocab, width = 137, 11
        permutation = random.permutation(vocab)
        inverse = np.argsort(permutation)
        original = random.normal(size=(vocab, width))
        converted = original[inverse]
        tokens = np.array([0, 1, 7, vocab - 1])
        np.testing.assert_array_equal(converted[permutation[tokens]], original[tokens])
        hidden = random.normal(size=width)
        np.testing.assert_allclose((converted @ hidden)[permutation], original @ hidden)
        np.testing.assert_array_equal(inverse[permutation[tokens]], tokens)

    def test_ple_operands_and_projection(self):
        random = np.random.default_rng(914)
        vocab = 137
        permutation = random.permutation(vocab)
        multipliers = [0x9E3779B97F4A7C15, 0xBF58476D1CE4E5B9, 0x94D049BB133111EB]
        mask = 2**64 - 1
        def signed(value):
            value &= mask
            return value - 2**64 if value >= 2**63 else value
        table = np.empty((vocab, 3), dtype=np.int64)
        for t in range(vocab):
            table[permutation[t]] = [signed(t * factor) for factor in multipliers]
        for now, previous, older in ((0, 0, 0), (136, 2, 7), (13, 136, 1)):
            original = signed((now * multipliers[0] & mask) ^
                              (previous * multipliers[1] & mask) ^
                              (older * multipliers[2] & mask))
            transformed = int(table[permutation[now], 0] ^ table[permutation[previous], 1]
                              ^ table[permutation[older], 2])
            for modulus in (17, 31, 67):
                self.assertEqual(transformed % modulus, original % modulus)
        width = 19
        p = random.permutation(width)
        signs = random.choice([-1, 1], size=width)
        transform = np.eye(width)[p] * signs[:, None]
        feature = random.normal(size=width)
        projection = random.normal(size=(7, width))
        np.testing.assert_allclose((projection @ transform.T) @ (transform @ feature),
                                   projection @ feature, atol=1e-12)

    def test_etc_affine_and_secret_order(self):
        random = np.random.default_rng(915)
        width, count = 27, 12
        pixels = random.integers(0, 256, size=(width, count)).astype(np.float64)
        mu = random.uniform(0.1, 0.8, size=width)
        sigma = random.uniform(0.2, 0.7, size=width)
        mapping = random.permutation(width)
        signs = random.choice([-1, 1], size=width)
        normalized = (pixels / 255 - mu[:, None]) / sigma[:, None]
        protected_pixels = signs[:, None] * pixels[mapping] + (1 - signs[:, None]) * 255 / 2
        protected = (protected_pixels / 255 - mu[:, None]) / sigma[:, None]
        transform = np.eye(width)[mapping] * (signs * sigma[mapping] / sigma)[:, None]
        offset = (signs * mu[mapping] + (1 - signs) / 2 - mu) / sigma
        np.testing.assert_allclose(protected, transform @ normalized + offset[:, None], atol=1e-12)
        weight, bias = random.normal(size=(9, width)), random.normal(size=9)
        converted = weight @ np.linalg.inv(transform)
        converted_bias = bias - converted @ offset
        expected = weight @ normalized + bias[:, None]
        order = random.permutation(count)
        actual = converted @ protected[:, order] + converted_bias[:, None]
        np.testing.assert_allclose(actual[:, np.argsort(order)], expected, atol=1e-12)


class WireChecks(unittest.IsolatedAsyncioTestCase):
    def test_codec_validation(self):
        message = {'type': 'generate', 'profile': 'fixture'}
        blobs = [b'', bytes(range(256))]
        self.assertEqual(wire.unpack(wire.pack(message, blobs)), (message, blobs))
        for raw in (b'', b'\0', wire.pack(message, blobs) + b'extra'):
            with self.assertRaises(ValueError):
                wire.unpack(raw)
        headers = [b'{"blob_lengths":[],"x":1,"x":2}',
                   b'{"blob_lengths":[true]}', b'{"blob_lengths":[],"x":NaN}',
                   b'{"blob_lengths":[],"x":1e999}', b'[]']
        for header in headers:
            with self.assertRaises(ValueError):
                wire.unpack(struct.pack('<I', len(header)) + header)

    async def test_chunks_and_shared_bidirectional_rate(self):
        class Socket:
            def __init__(self):
                self.pieces = []
                self.events = []
            async def send(self, data):
                self.events.append((time.monotonic(), len(data)))
                self.pieces.append(data)
            async def recv(self):
                return self.pieces.pop(0)
        rate = 400
        upload, download = wire.WindowLimiter(rate), wire.WindowLimiter(rate)
        sockets = [Socket() for _ in range(4)]
        channels = [wire.Channel(socket, upload=upload if i < 2 else download)
                    for i, socket in enumerate(sockets)]
        started = time.monotonic()
        await asyncio.gather(*(channel.send({'type': 'fixture'}, [bytes(300)]) for channel in channels))
        self.assertGreaterEqual(time.monotonic() - started, 0.99)
        for group, limit in ((sockets[:2], rate), (sockets[2:], rate), (sockets, 2 * rate)):
            events = sorted(event for socket in group for event in socket.events)
            window = deque()
            used = 0
            for now, size in events:
                while window and window[0][0] <= now - 1:
                    used -= window.popleft()[1]
                window.append((now, size))
                used += size
                self.assertLessEqual(used, limit)
        for socket in sockets:
            self.assertEqual(await wire.Channel(socket).recv(), ({'type': 'fixture'}, [bytes(300)]))
        fragmented = Socket()
        await wire.Channel(fragmented, upload=wire.WindowLimiter(400)).send({'type': 'fixture'}, [bytes(600)])
        self.assertEqual([piece[0] for piece in fragmented.pieces], [0, 1])
        self.assertEqual(await wire.Channel(fragmented).recv(), ({'type': 'fixture'}, [bytes(600)]))


class InspectionChecks(unittest.TestCase):
    def test_headers_exclusions_and_links(self):
        with tempfile.TemporaryDirectory(prefix='checkpoint-reference-') as temporary:
            root = Path(temporary)
            header = json.dumps({'token_embedding.weight': {'dtype': 'U8', 'shape': [4, 2],
                                                            'data_offsets': [0, 8]}}).encode()
            (root / 'target.safetensors').write_bytes(struct.pack('<Q', len(header)) + header + bytes(8))
            (root / 'index.json').write_text(json.dumps({'weight_map': {'token_embedding.weight': 'target.safetensors'}}))
            result = checkpoint.inspect(root, ['target=index.json'], {'bkp'}, True)
            self.assertEqual(result['roles']['target'], {'tensor_count': 1, 'tensor_bytes': 8})
            self.assertEqual(result['unindexed_tensors'], {})
            self.assertEqual(result['sensitive_candidates'][0]['shape'], [4, 2])
            extra = root / 'extra.safetensors'
            extra.write_bytes((root / 'target.safetensors').read_bytes())
            with self.assertRaises(ValueError):
                checkpoint.inspect(root, ['target=index.json'], {'bkp'}, True)
            extra.unlink()
            with self.assertRaises(ValueError):
                checkpoint.member(root, 'bkp/never-opened', {'bkp'})
            with self.assertRaises(ValueError):
                checkpoint.member(root, '../never-opened', {'bkp'})
            (root / 'linked').symlink_to(root / 'target.safetensors')
            with self.assertRaises(ValueError):
                checkpoint.member(root, 'linked', {'bkp'})
            with self.assertRaises(ValueError):
                checkpoint.inspect(root, ['target=index.json'], {'bkp'}, True)




class ImageEnvelopeChecks(unittest.TestCase):
    def test_public_v3_vector(self):
        v=json.loads((Path(__file__).resolve().parents[1]/'assets/image_v3_test_vector.json').read_text())
        t=v['image_transport'];password=v['password'].encode();profile=v['profile']
        key=hashlib.scrypt(password,salt=image_transport.image_kdf_salt(bytes.fromhex(t['salt']),profile),n=32768,r=8,p=1,dklen=32,maxmem=64*1024*1024)
        auth=wire.derive(v['password'],bytes.fromhex(v['auth_salt']))
        tokens=struct.pack('<III',*v['token_ids']);nonce=bytes.fromhex(v['nonce_hex'])
        aad=image_transport.image_aad(bytes.fromhex(v['challenge']),profile,tokens,0,0,v['descriptor'])
        payload=bytes((29*i+7)%256 for i in range(28*28*3))+struct.pack('<IIII',*v['patch_order'])
        envelope=nonce+AESGCM(key).encrypt(nonce,payload,aad)
        self.assertEqual(key.hex(),v['image_key_hex'])
        self.assertEqual(wire.proof(auth,bytes.fromhex(v['challenge']),profile,t),v['auth_proof'])
        self.assertEqual(hashlib.sha256(aad).hexdigest(),v['aad_sha256'])
        self.assertEqual(len(envelope),v['envelope_bytes'])
        self.assertEqual(hashlib.sha256(envelope).hexdigest(),v['envelope_sha256'])
        meta={'type':'generate','version':3,'profile':profile,'images':[v['descriptor']],'sampling':{'max_tokens':1}}
        manifest={'profile':profile,'vocab':100,'specials':{'image_token_id':88}}
        args=(manifest,'minicpm',bytes.fromhex(v['challenge']),1)
        self.assertEqual(image_transport.bind_request(meta,[tokens,envelope],*args,1)[1],2)
        with self.assertRaises(ValueError):image_transport.bind_request(meta,[tokens,envelope],*args,2)
        with self.assertRaises(ValueError):image_transport.bind_request(dict(meta,version=2),[tokens,envelope],*args,1)
        with self.assertRaises(InvalidTag):AESGCM(key).decrypt(nonce,envelope[12:],aad+b'x')


if __name__ == '__main__':
    unittest.main(verbosity=2)
