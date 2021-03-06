import z3
from .esilclasses import *
from .r2api import R2API

BYTE = 8

class ESILMemory:
    """ 
    Provides access to methods to read and write memory

    >>> state.memory[0xcafebabe]
    31337

    """

    def __init__(self, r2api: R2API, info: Dict, sym=False, check=False):
        self._memory = {}
        self._read_cache = {}
        self.r2api = r2api
        self.info = info
        self.pure_symbolic = sym
        self.default_addr = 0x100000
        self.check_perms = check

        self.hit_symbolic_addr = False
        self.concrete_addrs = []

        self._refs = {"count": 1}

        self.endian = info["info"]["endian"]
        self.bits = info["info"]["bits"]
        self.chunklen = int(self.bits/8)

        self.solver = None

    def mask(self, addr: int):
        return int(addr - (addr % self.chunklen))

    def bv_to_int(self, bv):

        bv = z3.simplify(bv)
        if z3.is_bv_value(bv):
            return bv.as_long()

        # this is terrible and temporary
        elif z3.is_bv(bv):
            #print("symbolic addr: %s" % bv)
            self.hit_symbolic_addr = True
            if self.solver.check() == z3.sat:
                model = self.solver.model()

                val = model.eval(bv, model_completion=True)
                self.solver.add(bv == val)
                return val.as_long()

            else:
                raise ESILUnsatException("no sat symbolic address found")

    def read(self, addr: int, length: int):

        if self.check_perms:
            self.check(addr, "r")

        maddr = self.mask(addr)
        #print(maddr, length)

        data = []
        chunks = int(length/self.chunklen) + min(1, length%self.chunklen)
        #print(chunks)

        for chunk in range(chunks):
            caddr = maddr + chunk*self.chunklen
            if caddr in self._memory:
                data += self._memory[caddr]

            else:
                if self.pure_symbolic:
                    coffset = caddr+chunk*self.chunklen
                    bv = z3.BitVec("mem_%016x" % (coffset), self.chunklen*BYTE)
                    self.write_bv(addr, bv, self.chunklen)
                    d = self.unpack_bv(bv, self.chunklen)
                else:
                    if caddr in self._read_cache:
                        d = self._read_cache[caddr]
                    else:
                        d = self.r2api.read(caddr, self.chunklen)
                        self._read_cache[caddr] = d

                    self._memory[caddr] = d

                data += d

        offset = addr-maddr
        return data[offset:offset+length]


    def write(self, addr, data):

        if self._refs["count"] > 1:
            self.finish_clone()

        if type(addr) != int:
            addr = self.bv_to_int(addr)

        if self.check_perms:
            self.check(addr, "w")

        if z3.is_bv(data):
            length = int(data.size()/BYTE)
            data = self.unpack_bv(data, length)
        elif type(data) == bytes:
            data = list(data)
        elif type(data) == str:
            data = list(data.encode())+[0] # add null byte
        elif type(data) == int:
            data = self.unpack_bv(data, int(self.bits/8))

        data = self.prepare_data(data)
        maddr = self.mask(addr)
        offset = addr-maddr
        length = len(data)

        if maddr != addr or length % self.chunklen != 0:
            prev_len = length + (self.chunklen - (length % self.chunklen))
            prev = self.read(maddr, prev_len)
            data = prev[:offset] + data + prev[offset+length:]

        chunks = int(length/self.chunklen) + min(1, length%self.chunklen)
        for chunk in range(chunks):
            o = chunk*self.chunklen
            caddr = maddr + o

            self._memory[caddr] = data[o:o+self.chunklen]

    def read_bv(self, addr, length):
        if type(addr) != int:
            addr = self.bv_to_int(addr)

        data = self.read(addr, length)
        bve = []

        if all(type(x) == int for x in data):
            bv = self.pack_bv(data)
            return bv 

        for datum in data:
            if type(datum) == int:
                bve.append(z3.BitVecVal(datum, BYTE))

            else:
                bve.append(datum)

        if self.endian == "little":
            bve.reverse()

        #print(bve)
        if len(bve) > 1:
            bv = z3.simplify(z3.Concat(*bve))
        else:
            bv = z3.simplify(bve[0])

        return bv

    def write_bv(self, addr, val, length: int):
        if type(addr) != int:
            addr = self.bv_to_int(addr)

        data = self.unpack_bv(val, length)
        self.write(addr, data)

    def pack_bv(self, data):
        val = 0
        for ind, dat in enumerate(data):
            val += dat << BYTE*ind

        return z3.BitVecVal(val, BYTE*len(data))

    def unpack_bv(self, val, length: int):
        if type(val) == int:
            data = [(val >> i*BYTE) & 0xff for i in range(length)]

        else:
            val = z3.simplify(val) # useless?
            data = [z3.Extract((i+1)*8-1, i*8, val) for i in range(length)]

        if self.endian == "big":
            data.reverse()

        return data

    def prepare_data(self, data):
        return data

    def check(self, addr, perm):
        perm_names = {
            "r": "read",
            "w": "write",
            "x": "execute"
        }

        perms = self.r2api.get_permissions(addr)
        if perm not in perms:
            raise ESILSegmentFault("failed to %s 0x%x (%s)" \
                % (perm_names[perm], addr, perms))

    def init_memory(self):
        pass

    def __getitem__(self, addr) -> z3.BitVecRef:
        if type(addr) == int:
            length = self.chunklen
            return self.read_bv(addr, length)
        elif type(addr) == slice:
            length = int(addr.stop-addr.start)
            return self.read_bv(addr.start, length)

    def __setitem__(self, addr, value):
        if type(addr) == int:
            return self.write(addr, value)
        elif type(addr) == slice:
            length = int(addr.stop-addr.start)

            if type(value) == list:
                self.write(addr.start, value[:length])
            elif z3.is_bv(value):
                new_val = z3.Extract(length*8 - 1, 0, value)
                self.write(addr.start, new_val)

    def __contains__(self, addr: int) -> bool:
        return addr in self._memory

    def __iter__(self): 
        return iter(self._memory.keys())

    def clone(self):
        clone = self.__class__(self.r2api, self.info, self.pure_symbolic)
        self._refs["count"] += 1
        clone._refs = self._refs
        clone._memory = self._memory
        clone._read_cache = self._read_cache

        return clone

    def finish_clone(self):
        # we can do a shallow copy instead of deep
        self._memory = self._memory.copy()
        self._refs["count"] -= 1
        self._refs = {"count": 1}