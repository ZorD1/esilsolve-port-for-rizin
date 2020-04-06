import r2pipe
import binascii

class R2API:

    def __init__(self, r2p=None, filename="-", flags=["-2"]):
        self.r2p = r2p
        if r2p == None:
            self.r2p = r2pipe.open(filename, flags=flags)

        self.instruction_cache = {}

        self.get_register_info()

    def get_info(self):
        return self.r2p.cmdj("iaj")

    def get_register_info(self):
        self.register_info = self.r2p.cmdj("aerpj")

        # uhhh wtf
        '''regs = []
        for reg in self.register_info["reg_info"]:
            if not ((reg["name"][0] == "d" and reg["name"][1:].isdigit()) or reg["name"] == "dsp"):
                regs.append(reg)
                
        self.register_info["reg_info"] = regs'''
        
        self.all_regs = [r["name"] for r in self.register_info["reg_info"]] 
        return self.register_info

    def get_reg_value(self, reg):
        return int(self.r2p.cmd("aer %s" % reg), 16)

    def get_gpr_values(self):
        return self.r2p.cmdj("aerj")

    def seek(self, addr):
        self.r2p.cmd("s %d" % addr)

    def step(self, sz):
        self.r2p.cmd("s+ %d" % sz)

    def disass(self, addr=None, instrs=1):
        if addr in self.instruction_cache and instrs == 1:
            return self.instruction_cache[addr]

        cmd = "pdj %d" % instrs
        if addr != None:
            cmd += " @ %d" % addr

        result = self.r2p.cmdj(cmd)

        for instr in result:
            self.instruction_cache[instr["offset"]] = instr

        if instrs == 1:
            return result[0]

        return result

    def read(self, addr, length):
        return self.r2p.cmdj("xj %d @ %d" % (length, addr))

    def write(self, addr, value, length=None, fill="0"):
        val = value
        if type(value) == int:
            return self.r2p.cmd("wv %d @ %d" % (value, addr))

        elif type(value) == bytes:
            val = binascii.hexlify(value).decode()

        if length != None:
            val = val.rjust(length, str(fill))

        return self.r2p.cmd("wx %s @ %d" % (val, addr))

    # theres no arj all function to get all the regs as json so i made this
    # i should just make a pull request for r2
    def get_all_registers(self):
        reg_dict = {}
        reg_str = ",".join(self.all_regs)
        val_str = self.r2p.cmd("aer %s" % reg_str)
        # this got a little too long
        all_vals = list(map(lambda x: int(x, 16), val_str.split("\n")[:-1]))

        for i in range(len(all_vals)):
            reg_dict[self.all_regs[i]] = all_vals[i]

        return reg_dict

    def init_vm(self):
        self.r2p.cmd("aei; aeim")

    def emu(self, instr):
        self.r2p.cmd("ae %s" % instr["esil"])

    def emustep(self):
        self.r2p.cmd("aes")