#include "contract.h"
static_assert(__riscv_xlen == 32);
static_assert(sizeof(void*) * 8 == 32);
static_assert(sizeof(vortex::ai::MatmulArguments) == 56);
