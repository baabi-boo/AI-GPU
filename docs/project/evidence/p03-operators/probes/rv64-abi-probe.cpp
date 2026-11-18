#include "contract.h"
static_assert(__riscv_xlen == 64);
static_assert(sizeof(void*) * 8 == 64);
static_assert(sizeof(vortex::ai::MatmulArguments) == 56);
