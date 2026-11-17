"""Public v3 image-envelope contract. This module never decrypts image data."""
import hashlib
import hmac
import json
import math
import struct

VERSION=3
IMAGE_DOMAIN=b'private-image-v3\0'
AUTH_DOMAIN=b'private-v3\0'
FORMAT='etc-rgb-u8-q-le32-v1'
MAX_MESSAGE=128*1024*1024

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')

def image_kdf_salt(salt,profile):
    if not isinstance(salt,bytes) or len(salt)!=16 or len(profile)!=64:
        raise ValueError('InvalidImageKDF')
    return IMAGE_DOMAIN+salt+profile.encode('ascii')

def negotiation(salt,layout,prefix):
    if layout not in ('minicpm','qwen') or not 0<prefix<2**64:
        raise ValueError('InvalidImageTransport')
    return {'format':FORMAT,'cipher':'AES-256-GCM','salt':salt.hex(),
            'kdf':{'name':'scrypt','n':32768,'r':8,'p':1,'length':32},
            'nonce_prefix':prefix.to_bytes(8,'big').hex(),'layout':layout,
            'patch_size':14 if layout=='minicpm' else 16}

def auth_proof(key,nonce,profile,transport):
    if len(key)!=32 or len(nonce)!=32 or len(profile)!=64:
        raise ValueError('InvalidAuthentication')
    return hmac.new(key,AUTH_DOMAIN+nonce+profile.encode('ascii')+hashlib.sha256(canonical(transport)).digest(),hashlib.sha256).hexdigest()

def image_aad(challenge,profile,token_blob,image_index,tile_index,descriptor):
    if len(challenge)!=32 or len(profile)!=64:raise ValueError('InvalidImageContext')
    return (IMAGE_DOMAIN+challenge+profile.encode('ascii')+struct.pack('<II',image_index,tile_index)
            +hashlib.sha256(token_blob).digest()+hashlib.sha256(canonical(descriptor)).digest())

def tiles(images,layout):
    """Validate public geometry and yield image/tile indices and tile metadata."""
    if not isinstance(images,list) or len(images)>16:raise ValueError('InvalidImages')
    last=0
    for i,image in enumerate(images):
        if not isinstance(image,dict) or set(image)!={'offset','length','grid','tiles'}:
            raise ValueError('InvalidImageDescriptor')
        offset,length,grid=image['offset'],image['length'],image['grid']
        if type(offset)is not int or type(length)is not int or offset<last or length<1:
            raise ValueError('InvalidPlaceholder')
        last=offset+length
        if not isinstance(grid,list) or any(type(v)is not int for v in grid):raise ValueError('InvalidGrid')
        if layout=='minicpm':
            if len(grid)!=2 or any(v<0 or v>9 for v in grid):raise ValueError('InvalidGrid')
            gx,gy=grid
            if (gx==0)!=(gy==0) or gx*gy>9:raise ValueError('InvalidGrid')
            count=1+gx*gy;patch=14
        elif layout=='qwen':
            if len(grid)!=3 or grid[0]!=1 or any(v<2 or v%2 for v in grid[1:]) or grid[1]*grid[2]>4096:
                raise ValueError('InvalidGrid')
            count=1;patch=16
        else:raise ValueError('UnsupportedImageLayout')
        entries=image['tiles']
        if not isinstance(entries,list) or len(entries)!=count:raise ValueError('InvalidTiles')
        total=0
        for j,tile in enumerate(entries):
            if not isinstance(tile,dict) or set(tile)!={'width','height','suffix','tokens'}:raise ValueError('InvalidTile')
            w,h=tile['width'],tile['height']
            if any(type(v)is not int or v<2*patch or v%(2*patch) for v in (w,h)) or w*h>1024*1024:
                raise ValueError('InvalidImageSize')
            if layout=='minicpm':
                suffix=1 if not gx else (2 if j==0 else (5 if j==count-1 else (4 if j%gx==0 else 3)))
                expected=(w//28)*(h//28)+{1:1,2:2,3:2,4:3,5:1}[suffix]
            else:
                if (h//16,w//16)!=(grid[1],grid[2]):raise ValueError('InvalidGrid')
                suffix=0;expected=grid[1]*grid[2]//4
            if tile['suffix']!=suffix or tile['tokens']!=expected:raise ValueError('InvalidVisualTokens')
            total+=expected
            yield i,j,image,tile,3*w*h+4*(w//patch)*(h//patch)
        if total!=length:raise ValueError('InvalidPlaceholderLength')

def bind_request(meta,blobs,manifest,layout,challenge,prefix,next_sequence,max_context=32768):
    """Validate public envelopes at the gateway, before attaching IPC context."""
    import numpy as np
    if not isinstance(meta,dict) or set(meta)-{'type','version','profile','images','sampling','stop_token_ids'}:
        raise ValueError('UnsupportedFeature')
    if meta.get('type')!='generate' or meta.get('version')!=VERSION or meta.get('profile')!=manifest['profile']:
        raise ValueError('ProtocolMismatch')
    if not blobs or len(blobs[0])%4:raise ValueError('InvalidTokens')
    ids=np.frombuffer(blobs[0],dtype='<u4')
    if not 0<len(ids)<=max_context or np.any(ids>=manifest['vocab']):raise ValueError('InvalidTokens')
    settings=meta.get('sampling',{})
    if not isinstance(settings,dict) or set(settings)-{'max_tokens','temperature','top_p'}:raise ValueError('UnsupportedSampling')
    maximum=settings.get('max_tokens',4096)
    if type(maximum)is not int or not 1<=maximum<=32767 or len(ids)+maximum>max_context:raise ValueError('ContextLimit')
    for field,default,lo,hi in [('temperature',0,0,2),('top_p',1,.0001,1)]:
        value=settings.get(field,default)
        if type(value)not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('InvalidSampling')
    stops=meta.get('stop_token_ids',[])
    if not isinstance(stops,list) or len(stops)>64 or any(type(v)is not int or not 0<=v<manifest['vocab'] for v in stops):raise ValueError('InvalidStops')
    entries=list(tiles(meta.get('images',[]),layout))
    if len(blobs)!=1+len(entries):raise ValueError('InvalidBlobs')
    for (i,j,image,tile,size),envelope in zip(entries,blobs[1:]):
        start=image['offset'];end=start+image['length']
        if end>len(ids) or not np.all(ids[start:end]==manifest['specials']['image_token_id']):
            raise ValueError('InvalidPlaceholder')
        if len(envelope)!=size+28:raise ValueError('InvalidEncryptedImageSize')
        if next_sequence>=2**32:raise ValueError('ImageCounterExhausted')
        nonce=prefix.to_bytes(8,'big')+next_sequence.to_bytes(4,'big')
        if envelope[:12]!=nonce:raise ValueError('InvalidImageNonce')
        next_sequence+=1
    copied=dict(meta)
    copied['_transport']={'challenge':challenge.hex(),'prefix':prefix}
    return copied,next_sequence

def worker_envelopes(meta,blobs,layout):
    context=meta['_transport'];challenge=bytes.fromhex(context['challenge'])
    entries=list(tiles(meta.get('images',[]),layout))
    if len(blobs)!=1+len(entries):raise ValueError('InvalidBlobs')
    for (i,j,image,tile,size),envelope in zip(entries,blobs[1:]):
        if len(envelope)!=size+28 or int.from_bytes(envelope[:8],'big')!=context['prefix']:
            raise ValueError('InvalidEncryptedImage')
        aad=image_aad(challenge,meta['profile'],blobs[0],i,j,image)
        yield i,j,image,tile,envelope,aad
