# [terminal-bench] extract-elf: example address in the instruction contradicts the reference solution for the shipped PIE binary

**Task:** `extract-elf` (terminal-bench 2.1)

**Problem.** The instruction shows `{"4194304": ..., "4194308": ...}` as the example output. 4194304 = 0x400000 is the classic non-PIE load base, so a solver reasonably infers "add 0x400000 to the ELF virtual addresses". But the reference implementation embedded in `tests/test_outputs.py` (`REF`) keys values by the raw section header address (`sh_addr`) of `.text/.data/.rodata` with **no load bias**, and the shipped `a.out` is a PIE (`ET_DYN`, sections at 0x1000/0x2000/0x4000). Under the reference rule the example addresses cannot occur for this binary. The test also compiles a fresh `new.c` with the system gcc (PIE by default), so any solution that follows the example gets 0% key overlap.

**Evidence.** 6/6 attempts by one model (Seed 2.1 lite) failed with `Only found 0.00% of expected values`; every trajectory hard-coded `BASE = 0x400000` after reading the example. With the following clarifications added to the instruction and nothing else changed, the same model passed 3/3:

- take `.text`, `.data`, `.rodata` only; read 4-byte unsigned little-endian words; key = `sh_addr + offset` in decimal, with no load-time relocation or PIE bias;
- the script is also run on a different gcc-compiled binary.

**Suggested fix.** Either state the addressing convention (as above) or change the example to addresses consistent with the shipped binary (e.g. `{"4096": ..., "4100": ...}`), or ship a non-PIE `a.out`.
