// SPDX-License-Identifier: Apache-2.0

#include <ai_matmul_args.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace va = vortex::ai;
using Bytes = std::array<uint8_t, 56>;
static unsigned checks = 0;

static void require(bool condition) {
  ++checks;
  if (!condition) {
    std::fprintf(stderr, "FAIL check=%u\n", checks);
    std::exit(1);
  }
}

static Bytes fixture() {
  return {{
    1, 0, 0, 0, 56, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0,
    8, 0, 0, 0, 4, 0, 0, 0, 8, 0, 0, 0, 0, 0, 0, 0,
    0x80, 0x70, 0x60, 0x50, 0x40, 0x30, 0x20, 0x10,
    0x80, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11,
    0x80, 0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22,
  }};
}

static void put32(Bytes* bytes, size_t offset, uint32_t value) {
  for (size_t i = 0; i < 4; ++i) {
    (*bytes)[offset + i] = static_cast<uint8_t>(value >> (i * 8));
  }
}

static void put64(Bytes* bytes, size_t offset, uint64_t value) {
  for (size_t i = 0; i < 8; ++i) {
    (*bytes)[offset + i] = static_cast<uint8_t>(value >> (i * 8));
  }
}

static void rejected(const Bytes& bytes, uint32_t dtype = 1, size_t size = 56) {
  va::MatmulArguments output;
  output.flags = 0x13579bdf;
  output.a_address = 0xfedcba9876543210;
  const auto before = output;
  require(!va::decode_matmul_arguments(bytes.data(), size, dtype, &output));
  require(std::memcmp(&before, &output, sizeof(output)) == 0);
}

static void literal() {
  const auto bytes = fixture();
  va::MatmulArguments out;
  require(va::decode_matmul_arguments(bytes.data(), bytes.size(), 1, &out));
  require(out.abi_version == 1 && out.byte_size == 56 && out.input_dtype == 1);
  require(out.flags == 0 && out.reserved == 0 && out.m == 8 && out.n == 4 && out.k == 8);
  require(out.a_address == 0x1020304050607080ull);
  require(out.b_address == 0x1122334455667780ull);
  require(out.d_address == 0x2233445566778880ull);
  std::array<uint8_t, 57> unaligned{};
  std::memcpy(unaligned.data() + 1, bytes.data(), bytes.size());
  va::MatmulArguments other;
  require(va::decode_matmul_arguments(unaligned.data() + 1, 56, 1, &other));
  require(std::memcmp(&out, &other, sizeof(out)) == 0);
}

static void signatures() {
  for (uint32_t dtype : {1u, 2u}) {
    for (const auto& dims : {std::array<uint32_t, 3>{8, 4, 8},
                             std::array<uint32_t, 3>{8, 4, 16},
                             std::array<uint32_t, 3>{16, 8, 16}}) {
      auto bytes = fixture();
      put32(&bytes, 8, dtype);
      put32(&bytes, 16, dims[0]);
      put32(&bytes, 20, dims[1]);
      put32(&bytes, 24, dims[2]);
      va::MatmulArguments out;
      require(va::decode_matmul_arguments(bytes.data(), bytes.size(), dtype, &out));
      require(out.input_dtype == dtype && out.m == dims[0] && out.n == dims[1] && out.k == dims[2]);
      rejected(bytes, 3 - dtype);
    }
  }
  for (const auto& dims : {std::array<uint32_t, 3>{16, 4, 16},
                           std::array<uint32_t, 3>{8, 8, 16},
                           std::array<uint32_t, 3>{16, 8, 8},
                           std::array<uint32_t, 3>{8, 4, 24},
                           std::array<uint32_t, 3>{0, 4, 8},
                           std::array<uint32_t, 3>{UINT32_MAX, UINT32_MAX, UINT32_MAX}}) {
    auto bytes = fixture();
    put32(&bytes, 16, dims[0]);
    put32(&bytes, 20, dims[1]);
    put32(&bytes, 24, dims[2]);
    rejected(bytes);
  }
}

static void invalid_headers() {
  const auto original = fixture();
  for (const auto& field : {std::array<uint32_t, 2>{0, 0}, {0, 2}, {4, 0}, {4, 55}, {4, 57},
                            {8, 0}, {8, 3}, {8, UINT32_MAX}, {12, 1}, {28, 1}}) {
    auto bytes = original;
    put32(&bytes, field[0], field[1]);
    rejected(bytes);
  }
  for (size_t size = 0; size < 56; ++size) {
    rejected(original, 1, size);
  }
  rejected(original, 1, 57);
  rejected(original, 0);
  rejected(original, 3);
  va::MatmulArguments out;
  const auto before = out;
  require(!va::decode_matmul_arguments(nullptr, 56, 1, &out));
  require(std::memcmp(&before, &out, sizeof(out)) == 0);
  require(!va::decode_matmul_arguments(original.data(), 56, 1, nullptr));
}

static void ranges() {
  for (size_t offset : {32u, 40u, 48u}) {
    for (uint64_t misalignment : {1u, 2u, 3u}) {
      auto bytes = fixture();
      put64(&bytes, offset, 0x1000 + misalignment);
      rejected(bytes);
    }
    const uint64_t operand_bytes = offset == 40 ? 64 : 128;
    auto bytes = fixture();
    put64(&bytes, offset, UINT64_MAX - (operand_bytes - 1));
    va::MatmulArguments out;
    require(va::decode_matmul_arguments(bytes.data(), bytes.size(), 1, &out));
    put64(&bytes, offset, UINT64_MAX - (operand_bytes - 1) + 4);
    rejected(bytes);
  }
  for (const auto& offsets : {std::array<size_t, 2>{32, 40}, {32, 48}, {40, 48}}) {
    auto bytes = fixture();
    put64(&bytes, offsets[0], 0x1000);
    put64(&bytes, offsets[1], 0x1000);
    rejected(bytes);
    const uint64_t operand_bytes = offsets[0] == 40 ? 64 : 128;
    put64(&bytes, offsets[1], 0x1000 + operand_bytes - 4);
    rejected(bytes);
    put64(&bytes, offsets[1], 0x1000 + operand_bytes);
    va::MatmulArguments out;
    require(va::decode_matmul_arguments(bytes.data(), bytes.size(), 1, &out));
  }
}

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  if (std::strcmp(argv[1], "literal") == 0) {
    literal();
  } else if (std::strcmp(argv[1], "signatures") == 0) {
    signatures();
  } else if (std::strcmp(argv[1], "headers") == 0) {
    invalid_headers();
  } else if (std::strcmp(argv[1], "ranges") == 0) {
    ranges();
  } else {
    return 2;
  }
  std::printf("PASS %s checks=%u\n", argv[1], checks);
  return 0;
}
