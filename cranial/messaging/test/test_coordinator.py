import logging
from time import time, sleep
from typing import Any, Dict, Iterator, List, Tuple  # noqa

from aioetcd3.client import Client
from aioetcd3.kv import KVMetadata


PREFIX = '/test/'
MsgId = int
Msg = Any


def _serial_producer(duration, mps=1000):
    """
    For testing. Produces sequential integers, each only once at a rate no
    greater than `mps`. This helps us test for reliability.

    >>> N = 1
    >>> M = 100
    >>> target = int(.9*N*M)
    >>> result = set()
    >>> for i, _ in _serial_producer(N, M):
    ...     result.add(i)
    >>> len(result) > target
    True
    >>> l = list(result)[:target]
    >>> mis = [i for i in range(target) if l[i] != i]
    >>> mis if len(mis) == 0 else l[mis[0]-5:mis[0]+5]
    []
    """
    starttime = time()
    i = 0
    while True:
        latest = time()
        if latest - starttime > duration:
            return
        yield i, None
        i += 1
        if time() - latest < 1/mps:
            sleep(1/mps)


def _producer(duration, mps=1000) -> Iterator[Tuple[MsgId, Msg]]:
    """
    For testing. Produces integers for `duration` seconds, repeating the same
    for up to 1/mps of a second. This helps us test for duplications.

    >>> N = 1
    >>> M = 200
    >>> target = int(.9*N*M)
    >>> result = set()
    >>> for i, _ in _producer(N, M):
    ...     result.add(i)
    >>> len(result) > target
    True
    >>> l = list(result)[:target]
    >>> l[:3]
    [0, 1, 2]
    >>> mis = [i for i in range(target) if l[i] != i]
    >>> mis if len(mis) == 0 else l[mis[0]-5:mis[0]+5]
    []
    """
    starttime = time()*mps
    i = 0
    while True:
        if i >= duration*mps:
            return
        i = int(time()*mps - starttime)
        yield i, None


class FakeMeta(KVMetadata):
    mod_revision = 0

    def __init__(self, rev):
        self.mod_revision = rev

    def __repr__(self):
        return '<mod_revision: {}>'.format(self.mod_revision)


class FakeClient(Client):
    rev = 0
    store = {}  # type: Dict[str, str]
    leases = {}  # type: Dict[float, List[str]]

    def __init__(self, prefix=PREFIX, endpoint=None):
        self.p = prefix
        self.store = {}
        self.leases = {}
        self.rev = 0

    async def preload(self):
        # Initial testing data.
        await self.put(self.p+'init', '1')
        await self.put(self.p+'parts/total', '6')
        await self.put(self.p+'parts/a', '1,2,5,0')
        await self.put(self.p+'parts/b', '3,4')
        await self.put(self.p+'checkpoint/1', '0,0')
        return self

    async def grant_lease(self, ttl: int):
        t = time() + ttl
        self.leases[t] = []
        return t

    async def range(self, r) -> List[Tuple[bytes, bytes, FakeMeta]]:
        # Delete expired keys.
        for t in self.leases:
            if t < time():
                for key in self.leases[t]:
                    del(self.store[key])
                del(self.leases[t])

        meta = FakeMeta(self.rev)
        self.rev += 1
        if type(r) is tuple:
            r = r[0]
        logging.debug('range %s', r)
        return [(bytes(k, 'utf-8'),
                 bytes(v, 'utf-8'),
                 meta)
                for k, v in self.store.items() if k.startswith(r)]

    async def put(self, key, value, lease=None):
        # logging.debug('Putting %s => %s', key, value)
        self.store[str(key)] = str(value)
        if lease:
            self.leases[lease] = str(key)

        # Simulate worker 'a' responding to requests.
        if key == self.p+'req/a':
            logging.debug(value)
            requestor, part, rev = value.split(',')
            if part in self.store[self.p+'parts/a'].split(','):
                self.store['{}checkpoint/{}'.format(self.p, part)] = '42'
                self.store['{}ack/{}/a/{}'.format(
                    self.p, requestor, part)] = rev
            else:
                self.store[self.p+'deny/'+requestor] = 'a,{},{}'.format(
                    part, rev)
            logging.debug('Store after request to `a`: %s', self.store)

    async def delete(self, key):
        del(self.store[key])


def _fake_client(prefix=PREFIX) -> Client:
    return FakeClient(prefix)
