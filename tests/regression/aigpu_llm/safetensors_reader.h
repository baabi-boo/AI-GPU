// SPDX-License-Identifier: Apache-2.0

#ifndef AIGPU_LLM_SAFETENSORS_READER_H
#define AIGPU_LLM_SAFETENSORS_READER_H

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace aigpu::llm {

constexpr uint64_t kSafetensorsMaxHeaderBytes = 100ULL * 1024ULL * 1024ULL;

struct SafetensorsTensor {
  std::string name;
  std::string dtype;
  std::vector<uint64_t> shape;
  uint64_t begin_offset = 0;
  uint64_t end_offset = 0;
  std::vector<uint8_t> raw_bytes;
};

namespace detail {

inline uint64_t read_u64_le(const uint8_t* p) noexcept {
  uint64_t v = 0;
  for (uint32_t i = 0; i < 8; ++i) {
    v |= uint64_t{p[i]} << (8 * i);
  }
  return v;
}

inline void write_u64_le(uint8_t* p, uint64_t v) noexcept {
  for (uint32_t i = 0; i < 8; ++i) {
    p[i] = static_cast<uint8_t>((v >> (8 * i)) & 0xffu);
  }
}

inline uint32_t read_u32_le(const uint8_t* p) noexcept {
  return uint32_t{p[0]}
       | (uint32_t{p[1]} << 8)
       | (uint32_t{p[2]} << 16)
       | (uint32_t{p[3]} << 24);
}

inline void write_u32_le(uint8_t* p, uint32_t v) noexcept {
  p[0] = static_cast<uint8_t>(v & 0xffu);
  p[1] = static_cast<uint8_t>((v >> 8) & 0xffu);
  p[2] = static_cast<uint8_t>((v >> 16) & 0xffu);
  p[3] = static_cast<uint8_t>((v >> 24) & 0xffu);
}

inline uint16_t read_u16_le(const uint8_t* p) noexcept {
  return static_cast<uint16_t>(uint16_t{p[0]} | (uint16_t{p[1]} << 8));
}

inline void write_u16_le(uint8_t* p, uint16_t v) noexcept {
  p[0] = static_cast<uint8_t>(v & 0xffu);
  p[1] = static_cast<uint8_t>((v >> 8) & 0xffu);
}

inline uint32_t float_to_bits(float v) noexcept {
  uint32_t bits = 0;
  std::memcpy(&bits, &v, sizeof(bits));
  return bits;
}

inline float bits_to_float(uint32_t bits) noexcept {
  float v = 0.0f;
  std::memcpy(&v, &bits, sizeof(v));
  return v;
}

inline float fp16_bits_to_f32(uint16_t h) noexcept {
  const uint32_t sign = (static_cast<uint32_t>(h) & 0x8000u) << 16;
  const uint32_t exp = (static_cast<uint32_t>(h) >> 10) & 0x1fu;
  uint32_t frac = static_cast<uint32_t>(h) & 0x03ffu;
  if (exp == 0u) {
    if (frac == 0u) {
      return bits_to_float(sign);
    }
    int32_t shift = -1;
    while ((frac & 0x0400u) == 0u) {
      frac <<= 1;
      ++shift;
    }
    frac &= 0x03ffu;
    const uint32_t f32_exp = static_cast<uint32_t>(127 - 15 - shift);
    return bits_to_float(sign | (f32_exp << 23) | (frac << 13));
  }
  if (exp == 0x1fu) {
    if (frac == 0u) {
      return bits_to_float(sign | 0x7f800000u);
    }
    return bits_to_float(sign | 0x7fc00000u | (frac << 13));
  }
  const uint32_t f32_exp = exp + (127u - 15u);
  return bits_to_float(sign | (f32_exp << 23) | (frac << 13));
}

inline float bf16_bits_to_f32(uint16_t b) noexcept {
  return bits_to_float(static_cast<uint32_t>(b) << 16);
}

inline bool dtype_byte_size(const std::string& dtype, uint64_t* out_size) noexcept {
  if (dtype == "F32") {
    *out_size = 4;
    return true;
  }
  if (dtype == "F16" || dtype == "BF16") {
    *out_size = 2;
    return true;
  }
  if (dtype == "I8" || dtype == "U8" || dtype == "BOOL") {
    *out_size = 1;
    return true;
  }
  if (dtype == "F64" || dtype == "I64" || dtype == "U64") {
    *out_size = 8;
    return true;
  }
  if (dtype == "I32" || dtype == "U32") {
    *out_size = 4;
    return true;
  }
  if (dtype == "I16" || dtype == "U16") {
    *out_size = 2;
    return true;
  }
  if (dtype == "F8_E4M3" || dtype == "F8_E5M2") {
    *out_size = 1;
    return true;
  }
  return false;
}

inline bool mul_u64_checked(uint64_t a, uint64_t b, uint64_t* out) noexcept {
  if (a != 0 && b > std::numeric_limits<uint64_t>::max() / a) {
    return false;
  }
  *out = a * b;
  return true;
}

inline std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  out.push_back('"');
  for (unsigned char ch : s) {
    if (ch == '"') {
      out += "\\\"";
    } else if (ch == '\\') {
      out += "\\\\";
    } else if (ch == '\b') {
      out += "\\b";
    } else if (ch == '\f') {
      out += "\\f";
    } else if (ch == '\n') {
      out += "\\n";
    } else if (ch == '\r') {
      out += "\\r";
    } else if (ch == '\t') {
      out += "\\t";
    } else if (ch < 0x20u) {
      char buf[8];
      std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned int>(ch));
      out += buf;
    } else {
      out.push_back(static_cast<char>(ch));
    }
  }
  out.push_back('"');
  return out;
}

class JsonCursor {
public:
  JsonCursor(const char* data, size_t size) noexcept
      : data_(data), size_(size), pos_(0) {}

  void skip_ws() noexcept {
    while (pos_ < size_) {
      const char ch = data_[pos_];
      if (ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n') {
        ++pos_;
      } else {
        break;
      }
    }
  }

  bool eof() const noexcept {
    return pos_ >= size_;
  }

  bool peek(char* out) noexcept {
    skip_ws();
    if (pos_ >= size_) {
      return false;
    }
    *out = data_[pos_];
    return true;
  }

  bool consume(char expected, std::string* err) {
    skip_ws();
    if (pos_ >= size_ || data_[pos_] != expected) {
      *err = std::string("expected '") + expected + "' in safetensors JSON header";
      return false;
    }
    ++pos_;
    return true;
  }

  bool parse_string(std::string* out, std::string* err) {
    skip_ws();
    if (pos_ >= size_ || data_[pos_] != '"') {
      *err = "expected JSON string";
      return false;
    }
    ++pos_;
    out->clear();
    while (pos_ < size_) {
      const unsigned char ch = static_cast<unsigned char>(data_[pos_++]);
      if (ch == '"') {
        return true;
      }
      if (ch < 0x20u) {
        *err = "unescaped control character in JSON string";
        return false;
      }
      if (ch != '\\') {
        out->push_back(static_cast<char>(ch));
        continue;
      }
      if (pos_ >= size_) {
        *err = "unterminated escape in JSON string";
        return false;
      }
      const char esc = data_[pos_++];
      switch (esc) {
        case '"':
        case '\\':
        case '/': {
          out->push_back(esc);
          break;
        }
        case 'b': {
          out->push_back('\b');
          break;
        }
        case 'f': {
          out->push_back('\f');
          break;
        }
        case 'n': {
          out->push_back('\n');
          break;
        }
        case 'r': {
          out->push_back('\r');
          break;
        }
        case 't': {
          out->push_back('\t');
          break;
        }
        case 'u': {
          if (pos_ + 4 > size_) {
            *err = "truncated \\u escape in JSON string";
            return false;
          }
          uint32_t cp = 0;
          for (int i = 0; i < 4; ++i) {
            const char hc = data_[pos_++];
            cp <<= 4;
            if (hc >= '0' && hc <= '9') {
              cp |= static_cast<uint32_t>(hc - '0');
            } else if (hc >= 'a' && hc <= 'f') {
              cp |= static_cast<uint32_t>(hc - 'a' + 10);
            } else if (hc >= 'A' && hc <= 'F') {
              cp |= static_cast<uint32_t>(hc - 'A' + 10);
            } else {
              *err = "invalid hex digit in \\u escape";
              return false;
            }
          }
          if (cp >= 0xd800u && cp <= 0xdbffu) {
            if (pos_ + 6 > size_ || data_[pos_] != '\\' || data_[pos_ + 1] != 'u') {
              *err = "unpaired UTF-16 high surrogate in JSON string";
              return false;
            }
            pos_ += 2;
            uint32_t lo = 0;
            for (int i = 0; i < 4; ++i) {
              const char hc = data_[pos_++];
              lo <<= 4;
              if (hc >= '0' && hc <= '9') {
                lo |= static_cast<uint32_t>(hc - '0');
              } else if (hc >= 'a' && hc <= 'f') {
                lo |= static_cast<uint32_t>(hc - 'a' + 10);
              } else if (hc >= 'A' && hc <= 'F') {
                lo |= static_cast<uint32_t>(hc - 'A' + 10);
              } else {
                *err = "invalid hex digit in UTF-16 low surrogate";
                return false;
              }
            }
            if (lo < 0xdc00u || lo > 0xdfffu) {
              *err = "invalid UTF-16 low surrogate in JSON string";
              return false;
            }
            cp = 0x10000u + (((cp - 0xd800u) << 10) | (lo - 0xdc00u));
          } else if (cp >= 0xdc00u && cp <= 0xdfffu) {
            *err = "unpaired UTF-16 low surrogate in JSON string";
            return false;
          }
          if (cp <= 0x7fu) {
            out->push_back(static_cast<char>(cp));
          } else if (cp <= 0x7ffu) {
            out->push_back(static_cast<char>(0xc0u | (cp >> 6)));
            out->push_back(static_cast<char>(0x80u | (cp & 0x3fu)));
          } else if (cp <= 0xffffu) {
            out->push_back(static_cast<char>(0xe0u | (cp >> 12)));
            out->push_back(static_cast<char>(0x80u | ((cp >> 6) & 0x3fu)));
            out->push_back(static_cast<char>(0x80u | (cp & 0x3fu)));
          } else {
            out->push_back(static_cast<char>(0xf0u | (cp >> 18)));
            out->push_back(static_cast<char>(0x80u | ((cp >> 12) & 0x3fu)));
            out->push_back(static_cast<char>(0x80u | ((cp >> 6) & 0x3fu)));
            out->push_back(static_cast<char>(0x80u | (cp & 0x3fu)));
          }
          break;
        }
        default: {
          *err = "unsupported escape sequence in JSON string";
          return false;
        }
      }
    }
    *err = "unterminated JSON string";
    return false;
  }

  bool parse_u64(uint64_t* out, std::string* err) {
    skip_ws();
    if (pos_ >= size_) {
      *err = "expected unsigned integer in JSON";
      return false;
    }
    const char first = data_[pos_];
    if (first < '0' || first > '9') {
      *err = "expected non-negative integer in JSON";
      return false;
    }
    if (first == '0') {
      ++pos_;
      if (pos_ < size_) {
        const char next = data_[pos_];
        if ((next >= '0' && next <= '9') || next == '.' || next == 'e' || next == 'E') {
          *err = "invalid integer token in JSON";
          return false;
        }
      }
      *out = 0;
      return true;
    }
    uint64_t val = 0;
    while (pos_ < size_) {
      const char ch = data_[pos_];
      if (ch < '0' || ch > '9') {
        break;
      }
      const uint64_t digit = static_cast<uint64_t>(ch - '0');
      if (val > (std::numeric_limits<uint64_t>::max() - digit) / 10ULL) {
        *err = "uint64 overflow in JSON integer";
        return false;
      }
      val = val * 10ULL + digit;
      ++pos_;
    }
    if (pos_ < size_ && (data_[pos_] == '.' || data_[pos_] == 'e' || data_[pos_] == 'E')) {
      *err = "expected exact integer without fraction or exponent";
      return false;
    }
    *out = val;
    return true;
  }

  bool parse_u64_array(std::vector<uint64_t>* out, std::string* err) {
    if (!consume('[', err)) {
      return false;
    }
    out->clear();
    char ch = '\0';
    if (!peek(&ch)) {
      *err = "unterminated JSON array";
      return false;
    }
    if (ch == ']') {
      ++pos_;
      return true;
    }
    while (true) {
      uint64_t v = 0;
      if (!parse_u64(&v, err)) {
        return false;
      }
      out->push_back(v);
      if (!peek(&ch)) {
        *err = "unterminated JSON array";
        return false;
      }
      if (ch == ',') {
        ++pos_;
        continue;
      }
      if (ch == ']') {
        ++pos_;
        return true;
      }
      *err = "expected ',' or ']' in JSON array";
      return false;
    }
  }

  bool skip_value(std::string* err, uint32_t depth = 0) {
    if (depth > 64u) {
      *err = "JSON nesting depth exceeded";
      return false;
    }
    char ch = '\0';
    if (!peek(&ch)) {
      *err = "unexpected end of JSON value";
      return false;
    }
    if (ch == '"') {
      std::string dummy;
      return parse_string(&dummy, err);
    }
    if (ch == '{') {
      ++pos_;
      if (!peek(&ch)) {
        *err = "unterminated JSON object";
        return false;
      }
      if (ch == '}') {
        ++pos_;
        return true;
      }
      while (true) {
        std::string key;
        if (!parse_string(&key, err) || !consume(':', err) || !skip_value(err, depth + 1)) {
          return false;
        }
        if (!peek(&ch)) {
          *err = "unterminated JSON object";
          return false;
        }
        if (ch == ',') {
          ++pos_;
          continue;
        }
        if (ch == '}') {
          ++pos_;
          return true;
        }
        *err = "expected ',' or '}' in JSON object";
        return false;
      }
    }
    if (ch == '[') {
      ++pos_;
      if (!peek(&ch)) {
        *err = "unterminated JSON array";
        return false;
      }
      if (ch == ']') {
        ++pos_;
        return true;
      }
      while (true) {
        if (!skip_value(err, depth + 1)) {
          return false;
        }
        if (!peek(&ch)) {
          *err = "unterminated JSON array";
          return false;
        }
        if (ch == ',') {
          ++pos_;
          continue;
        }
        if (ch == ']') {
          ++pos_;
          return true;
        }
        *err = "expected ',' or ']' in JSON array";
        return false;
      }
    }
    if (pos_ + 4 <= size_ && std::memcmp(data_ + pos_, "true", 4) == 0) {
      pos_ += 4;
      return true;
    }
    if (pos_ + 5 <= size_ && std::memcmp(data_ + pos_, "false", 5) == 0) {
      pos_ += 5;
      return true;
    }
    if (pos_ + 4 <= size_ && std::memcmp(data_ + pos_, "null", 4) == 0) {
      pos_ += 4;
      return true;
    }
    if (ch == '-' || (ch >= '0' && ch <= '9')) {
      if (data_[pos_] == '-') {
        ++pos_;
      }
      if (pos_ >= size_ || data_[pos_] < '0' || data_[pos_] > '9') {
        *err = "invalid JSON number";
        return false;
      }
      while (pos_ < size_ && data_[pos_] >= '0' && data_[pos_] <= '9') {
        ++pos_;
      }
      if (pos_ < size_ && data_[pos_] == '.') {
        ++pos_;
        if (pos_ >= size_ || data_[pos_] < '0' || data_[pos_] > '9') {
          *err = "invalid JSON number fraction";
          return false;
        }
        while (pos_ < size_ && data_[pos_] >= '0' && data_[pos_] <= '9') {
          ++pos_;
        }
      }
      if (pos_ < size_ && (data_[pos_] == 'e' || data_[pos_] == 'E')) {
        ++pos_;
        if (pos_ < size_ && (data_[pos_] == '+' || data_[pos_] == '-')) {
          ++pos_;
        }
        if (pos_ >= size_ || data_[pos_] < '0' || data_[pos_] > '9') {
          *err = "invalid JSON number exponent";
          return false;
        }
        while (pos_ < size_ && data_[pos_] >= '0' && data_[pos_] <= '9') {
          ++pos_;
        }
      }
      return true;
    }
    *err = "unexpected token in JSON";
    return false;
  }

  bool finish(std::string* err) {
    skip_ws();
    if (pos_ != size_) {
      *err = "trailing bytes after JSON header";
      return false;
    }
    return true;
  }

private:
  const char* data_;
  size_t size_;
  size_t pos_;
};

inline bool parse_metadata_object(JsonCursor* cur, std::map<std::string, std::string>* out,
                                  std::string* err) {
  if (!cur->consume('{', err)) {
    return false;
  }
  char ch = '\0';
  if (!cur->peek(&ch)) {
    *err = "unterminated __metadata__ object";
    return false;
  }
  if (ch == '}') {
    std::string dummy;
    return cur->consume('}', &dummy);
  }
  while (true) {
    std::string k;
    std::string v;
    if (!cur->parse_string(&k, err) || !cur->consume(':', err) || !cur->parse_string(&v, err)) {
      return false;
    }
    if (!out->emplace(std::move(k), std::move(v)).second) {
      *err = "duplicate key in __metadata__ object";
      return false;
    }
    if (!cur->peek(&ch)) {
      *err = "unterminated __metadata__ object";
      return false;
    }
    if (ch == ',') {
      if (!cur->consume(',', err)) {
        return false;
      }
      continue;
    }
    if (ch == '}') {
      return cur->consume('}', err);
    }
    *err = "expected ',' or '}' in __metadata__ object";
    return false;
  }
}

inline bool parse_tensor_entry(JsonCursor* cur, const std::string& name,
                               SafetensorsTensor* out, std::string* err) {
  out->name = name;
  out->dtype.clear();
  out->shape.clear();
  out->begin_offset = 0;
  out->end_offset = 0;

  if (!cur->consume('{', err)) {
    return false;
  }
  bool seen_dtype = false;
  bool seen_shape = false;
  bool seen_offsets = false;
  char ch = '\0';
  if (!cur->peek(&ch)) {
    *err = "unterminated tensor object";
    return false;
  }
  if (ch == '}') {
    *err = "empty tensor metadata object for '" + name + "'";
    return false;
  }
  while (true) {
    std::string field;
    if (!cur->parse_string(&field, err) || !cur->consume(':', err)) {
      return false;
    }
    if (field == "dtype") {
      if (seen_dtype) {
        *err = "duplicate dtype field for tensor '" + name + "'";
        return false;
      }
      if (!cur->parse_string(&out->dtype, err)) {
        return false;
      }
      seen_dtype = true;
    } else if (field == "shape") {
      if (seen_shape) {
        *err = "duplicate shape field for tensor '" + name + "'";
        return false;
      }
      if (!cur->parse_u64_array(&out->shape, err)) {
        return false;
      }
      seen_shape = true;
    } else if (field == "data_offsets") {
      if (seen_offsets) {
        *err = "duplicate data_offsets field for tensor '" + name + "'";
        return false;
      }
      std::vector<uint64_t> offsets;
      if (!cur->parse_u64_array(&offsets, err)) {
        return false;
      }
      if (offsets.size() != 2) {
        *err = "data_offsets must contain exactly 2 integers for '" + name + "'";
        return false;
      }
      out->begin_offset = offsets[0];
      out->end_offset = offsets[1];
      seen_offsets = true;
    } else {
      *err = "unexpected field '" + field + "' in tensor '" + name + "'";
      return false;
    }

    if (!cur->peek(&ch)) {
      *err = "unterminated tensor metadata object";
      return false;
    }
    if (ch == ',') {
      if (!cur->consume(',', err)) {
        return false;
      }
      continue;
    }
    if (ch == '}') {
      if (!cur->consume('}', err)) {
        return false;
      }
      break;
    }
    *err = "expected ',' or '}' in tensor metadata object";
    return false;
  }

  if (!seen_dtype || !seen_shape || !seen_offsets) {
    *err = "tensor '" + name + "' missing dtype, shape, or data_offsets";
    return false;
  }
  return true;
}

inline uint64_t splitmix64_next(uint64_t* state) noexcept {
  *state += 0x9E3779B97F4A7C15ULL;
  uint64_t z = *state;
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

inline std::vector<float> deterministic_stream(uint64_t seed, size_t count,
                                               double scale, double offset) {
  std::vector<float> vals(count);
  uint64_t state = seed;
  for (size_t i = 0; i < count; ++i) {
    const uint64_t z = splitmix64_next(&state);
    const double u = std::ldexp(static_cast<double>(z >> 40), -24) * 2.0 - 1.0;
    vals[i] = static_cast<float>(offset + u * scale);
  }
  return vals;
}

inline std::vector<uint8_t> encode_f32_le(const std::vector<float>& vals) {
  std::vector<uint8_t> out(vals.size() * 4);
  for (size_t i = 0; i < vals.size(); ++i) {
    write_u32_le(out.data() + i * 4, float_to_bits(vals[i]));
  }
  return out;
}

} // namespace detail

class SafetensorsFile {
public:
  static bool load(const std::string& path, SafetensorsFile* out, std::string* err,
                   bool strict_contiguous = true) {
    std::string local_err;
    std::string* err_out = err ? err : &local_err;
    err_out->clear();
    if (!out) {
      *err_out = "output SafetensorsFile pointer must not be null";
      return false;
    }

    std::ifstream ifs(path, std::ios::binary | std::ios::ate);
    if (!ifs.is_open()) {
      *err_out = "failed to open safetensors file: " + path;
      return false;
    }
    const std::ifstream::pos_type end_pos = ifs.tellg();
    if (end_pos < 0) {
      *err_out = "failed to query size of safetensors file: " + path;
      return false;
    }
    const uint64_t total_bytes = static_cast<uint64_t>(end_pos);
    if (total_bytes < 8ULL) {
      *err_out = "safetensors file smaller than 8-byte header prefix";
      return false;
    }
    ifs.seekg(0, std::ios::beg);
    std::vector<uint8_t> file_bytes(static_cast<size_t>(total_bytes));
    if (!ifs.read(reinterpret_cast<char*>(file_bytes.data()),
                  static_cast<std::streamsize>(total_bytes))) {
      *err_out = "failed to read safetensors file: " + path;
      return false;
    }
    return parse_bytes(file_bytes, out, err_out, strict_contiguous);
  }

  static bool parse_bytes(const std::vector<uint8_t>& bytes, SafetensorsFile* out,
                          std::string* err, bool strict_contiguous = true) {
    std::string local_err;
    std::string* err_out = err ? err : &local_err;
    err_out->clear();
    if (!out) {
      *err_out = "output SafetensorsFile pointer must not be null";
      return false;
    }
    out->tensors_.clear();
    out->metadata_.clear();

    const uint64_t total_bytes = static_cast<uint64_t>(bytes.size());
    if (total_bytes < 8ULL) {
      *err_out = "safetensors buffer smaller than 8-byte header prefix";
      return false;
    }
    const uint64_t header_len = detail::read_u64_le(bytes.data());
    if (header_len == 0ULL) {
      *err_out = "safetensors header length must be positive";
      return false;
    }
    if (header_len > kSafetensorsMaxHeaderBytes) {
      *err_out = "safetensors header length exceeds 100 MiB limit";
      return false;
    }
    if (header_len > total_bytes - 8ULL) {
      *err_out = "safetensors header extends past EOF";
      return false;
    }

    const uint64_t data_start = 8ULL + header_len;
    const uint64_t payload_len = total_bytes - data_start;

    detail::JsonCursor cur(reinterpret_cast<const char*>(bytes.data() + 8),
                           static_cast<size_t>(header_len));
    if (!cur.consume('{', err_out)) {
      return false;
    }

    char ch = '\0';
    if (!cur.peek(&ch)) {
      *err_out = "unterminated JSON header";
      return false;
    }

    std::vector<SafetensorsTensor> parsed_tensors;
    std::map<std::string, std::string> parsed_metadata;
    bool seen_metadata = false;

    if (ch != '}') {
      while (true) {
        std::string key;
        if (!cur.parse_string(&key, err_out) || !cur.consume(':', err_out)) {
          return false;
        }
        if (key.empty()) {
          *err_out = "tensor name must not be empty";
          return false;
        }
        if (key == "__metadata__") {
          if (seen_metadata) {
            *err_out = "duplicate __metadata__ key in safetensors header";
            return false;
          }
          if (!detail::parse_metadata_object(&cur, &parsed_metadata, err_out)) {
            return false;
          }
          seen_metadata = true;
        } else {
          SafetensorsTensor tensor;
          if (!detail::parse_tensor_entry(&cur, key, &tensor, err_out)) {
            return false;
          }
          uint64_t elem_bytes = 0;
          if (!detail::dtype_byte_size(tensor.dtype, &elem_bytes)) {
            *err_out = "unsupported dtype '" + tensor.dtype + "' for tensor '" + key + "'";
            return false;
          }
          uint64_t numel = 1;
          for (uint64_t dim : tensor.shape) {
            if (!detail::mul_u64_checked(numel, dim, &numel)) {
              *err_out = "shape element count overflow for tensor '" + key + "'";
              return false;
            }
          }
          uint64_t expected_bytes = 0;
          if (!detail::mul_u64_checked(numel, elem_bytes, &expected_bytes)) {
            *err_out = "byte length overflow for tensor '" + key + "'";
            return false;
          }
          if (tensor.begin_offset > tensor.end_offset) {
            *err_out = "non-monotonic data_offsets for tensor '" + key + "'";
            return false;
          }
          if (tensor.end_offset > payload_len) {
            *err_out = "data_offsets out of bounds for tensor '" + key + "'";
            return false;
          }
          if ((tensor.end_offset - tensor.begin_offset) != expected_bytes) {
            *err_out = "data_offsets span mismatch for tensor '" + key + "'";
            return false;
          }
          if (out->tensors_.find(key) != out->tensors_.end()) {
            *err_out = "duplicate tensor key '" + key + "' in safetensors header";
            return false;
          }
          parsed_tensors.push_back(std::move(tensor));
          out->tensors_.emplace(key, SafetensorsTensor{});
        }

        if (!cur.peek(&ch)) {
          *err_out = "unterminated JSON header";
          return false;
        }
        if (ch == ',') {
          if (!cur.consume(',', err_out)) {
            return false;
          }
          continue;
        }
        if (ch == '}') {
          if (!cur.consume('}', err_out)) {
            return false;
          }
          break;
        }
        *err_out = "expected ',' or '}' in safetensors JSON header";
        return false;
      }
    } else {
      if (!cur.consume('}', err_out)) {
        return false;
      }
    }

    if (!cur.finish(err_out)) {
      return false;
    }

    std::vector<const SafetensorsTensor*> ordered;
    ordered.reserve(parsed_tensors.size());
    for (const auto& t : parsed_tensors) {
      ordered.push_back(&t);
    }
    std::sort(ordered.begin(), ordered.end(),
              [](const SafetensorsTensor* a, const SafetensorsTensor* b) {
                if (a->begin_offset != b->begin_offset) {
                  return a->begin_offset < b->begin_offset;
                }
                if (a->end_offset != b->end_offset) {
                  return a->end_offset < b->end_offset;
                }
                return a->name < b->name;
              });

    uint64_t prev_end = 0;
    for (const SafetensorsTensor* t : ordered) {
      if (t->begin_offset < prev_end) {
        *err_out = "overlapping data_offsets at tensor '" + t->name + "'";
        return false;
      }
      if (strict_contiguous && t->begin_offset != prev_end) {
        *err_out = "unreferenced gap in safetensors payload before '" + t->name + "'";
        return false;
      }
      prev_end = t->end_offset;
    }
    if (strict_contiguous && prev_end != payload_len) {
      *err_out = "trailing unreferenced bytes in safetensors payload";
      return false;
    }

    out->tensors_.clear();
    for (auto& t : parsed_tensors) {
      const size_t begin = static_cast<size_t>(data_start + t.begin_offset);
      const size_t end = static_cast<size_t>(data_start + t.end_offset);
      t.raw_bytes.assign(bytes.begin() + static_cast<std::ptrdiff_t>(begin),
                         bytes.begin() + static_cast<std::ptrdiff_t>(end));
      out->tensors_.emplace(t.name, std::move(t));
    }
    out->metadata_ = std::move(parsed_metadata);
    return true;
  }

  bool has(const std::string& name) const noexcept {
    return tensors_.find(name) != tensors_.end();
  }

  const SafetensorsTensor* find(const std::string& name) const noexcept {
    const auto it = tensors_.find(name);
    return (it == tensors_.end()) ? nullptr : &it->second;
  }

  size_t num_tensors() const noexcept {
    return tensors_.size();
  }

  const std::map<std::string, std::string>& metadata() const noexcept {
    return metadata_;
  }

  bool read_as_f32(const std::string& name, const std::vector<uint64_t>& expected_shape,
                   std::vector<float>* out, std::string* err) const {
    const SafetensorsTensor* t = find(name);
    if (!t) {
      if (err) {
        *err = "missing required tensor '" + name + "'";
      }
      return false;
    }
    if (t->shape != expected_shape) {
      if (err) {
        *err = "shape mismatch for tensor '" + name + "'";
      }
      return false;
    }
    uint64_t numel = 1;
    for (uint64_t dim : t->shape) {
      numel *= dim;
    }
    out->resize(static_cast<size_t>(numel));
    if (t->dtype == "F32") {
      for (size_t i = 0; i < out->size(); ++i) {
        (*out)[i] = detail::bits_to_float(detail::read_u32_le(t->raw_bytes.data() + i * 4));
      }
      return true;
    }
    if (t->dtype == "F16") {
      for (size_t i = 0; i < out->size(); ++i) {
        (*out)[i] = detail::fp16_bits_to_f32(detail::read_u16_le(t->raw_bytes.data() + i * 2));
      }
      return true;
    }
    if (t->dtype == "BF16") {
      for (size_t i = 0; i < out->size(); ++i) {
        (*out)[i] = detail::bf16_bits_to_f32(detail::read_u16_le(t->raw_bytes.data() + i * 2));
      }
      return true;
    }
    if (err) {
      *err = "unsupported floating dtype '" + t->dtype + "' for tensor '" + name + "'";
    }
    return false;
  }

private:
  std::map<std::string, SafetensorsTensor> tensors_;
  std::map<std::string, std::string> metadata_;
};

struct MicroLlamaConfig {
  uint32_t vocab_size = 32;
  uint32_t n_layers = 2;
  uint32_t d_model = 16;
  uint32_t n_q_heads = 2;
  uint32_t n_kv_heads = 1;
  uint32_t d_head = 8;
  uint32_t d_ff = 16;
  uint32_t max_seq = 16;
  uint64_t seed = 0x4C4C414D415F5633ULL;
};

inline bool serialize_safetensors_map(
    const std::map<std::string, SafetensorsTensor>& tensors,
    const std::map<std::string, std::string>& metadata,
    std::vector<uint8_t>* out_blob,
    std::string* err) {
  std::ostringstream json;
  json << '{';
  bool first_entry = true;
  if (!metadata.empty()) {
    json << "\"__metadata__\":{";
    bool first_meta = true;
    for (const auto& kv : metadata) {
      if (!first_meta) {
        json << ',';
      }
      first_meta = false;
      json << detail::json_escape(kv.first) << ':' << detail::json_escape(kv.second);
    }
    json << '}';
    first_entry = false;
  }

  uint64_t offset = 0;
  std::vector<const SafetensorsTensor*> ordered;
  ordered.reserve(tensors.size());
  for (const auto& kv : tensors) {
    const SafetensorsTensor& t = kv.second;
    if (kv.first.empty() || kv.first == "__metadata__") {
      if (err) {
        *err = "invalid tensor key '" + kv.first + "'";
      }
      return false;
    }
    uint64_t elem_bytes = 0;
    if (!detail::dtype_byte_size(t.dtype, &elem_bytes)) {
      if (err) {
        *err = "unsupported dtype '" + t.dtype + "'";
      }
      return false;
    }
    uint64_t numel = 1;
    for (uint64_t d : t.shape) {
      if (!detail::mul_u64_checked(numel, d, &numel)) {
        if (err) {
          *err = "shape overflow";
        }
        return false;
      }
    }
    uint64_t expected_bytes = 0;
    if (!detail::mul_u64_checked(numel, elem_bytes, &expected_bytes)
        || expected_bytes != t.raw_bytes.size()) {
      if (err) {
        *err = "tensor byte size mismatch for '" + kv.first + "'";
      }
      return false;
    }
    const uint64_t end_offset = offset + expected_bytes;
    if (!first_entry) {
      json << ',';
    }
    first_entry = false;
    json << detail::json_escape(kv.first) << ":{\"dtype\":" << detail::json_escape(t.dtype)
         << ",\"shape\":[";
    for (size_t i = 0; i < t.shape.size(); ++i) {
      if (i > 0) {
        json << ',';
      }
      json << t.shape[i];
    }
    json << "],\"data_offsets\":[" << offset << ',' << end_offset << "]}";
    ordered.push_back(&t);
    offset = end_offset;
  }
  json << '}';

  std::string header_str = json.str();
  const size_t rem = (8u + header_str.size()) % 8u;
  if (rem != 0u) {
    header_str.append(8u - rem, ' ');
  }
  if (header_str.size() > kSafetensorsMaxHeaderBytes) {
    if (err) {
      *err = "serialized safetensors header exceeds limit";
    }
    return false;
  }

  out_blob->resize(8u + header_str.size() + static_cast<size_t>(offset));
  detail::write_u64_le(out_blob->data(), static_cast<uint64_t>(header_str.size()));
  std::memcpy(out_blob->data() + 8u, header_str.data(), header_str.size());
  size_t cursor = 8u + header_str.size();
  for (const SafetensorsTensor* t : ordered) {
    if (!t->raw_bytes.empty()) {
      std::memcpy(out_blob->data() + cursor, t->raw_bytes.data(), t->raw_bytes.size());
      cursor += t->raw_bytes.size();
    }
  }
  return true;
}

inline bool write_micro_llama_safetensors(const std::string& path,
                                          const MicroLlamaConfig& cfg = MicroLlamaConfig{},
                                          std::string* err = nullptr) {
  std::string local_err;
  std::string* err_out = err ? err : &local_err;
  if (cfg.vocab_size == 0 || cfg.n_layers == 0 || cfg.d_model == 0
      || cfg.n_q_heads == 0 || cfg.n_kv_heads == 0 || cfg.d_head == 0
      || cfg.d_ff == 0 || cfg.max_seq == 0
      || cfg.n_q_heads * cfg.d_head != cfg.d_model
      || (cfg.n_q_heads % cfg.n_kv_heads) != 0
      || (cfg.d_head & 1u) != 0) {
    *err_out = "invalid micro-Llama dimensions";
    return false;
  }

  const uint32_t kv_dim = cfg.n_kv_heads * cfg.d_head;
  std::map<std::string, SafetensorsTensor> tensors;
  uint64_t stream_seed = cfg.seed;

  auto add_f32 = [&](const std::string& name, const std::vector<uint64_t>& shape,
                     double scale, double offset) {
    ++stream_seed;
    uint64_t numel = 1;
    for (uint64_t d : shape) {
      numel *= d;
    }
    SafetensorsTensor t;
    t.name = name;
    t.dtype = "F32";
    t.shape = shape;
    t.raw_bytes = detail::encode_f32_le(
        detail::deterministic_stream(stream_seed, static_cast<size_t>(numel), scale, offset));
    tensors.emplace(name, std::move(t));
  };

  add_f32("tok_embeddings.weight", {cfg.vocab_size, cfg.d_model}, 0.35, 0.0);
  for (uint32_t l = 0; l < cfg.n_layers; ++l) {
    const std::string prefix = "layers." + std::to_string(l) + ".";
    add_f32(prefix + "attention_norm.weight", {cfg.d_model}, 0.25, 0.85);
    add_f32(prefix + "wq.weight", {cfg.d_model, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "wk.weight", {kv_dim, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "wv.weight", {kv_dim, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "wo.weight", {cfg.d_model, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "ffn_norm.weight", {cfg.d_model}, 0.25, 0.85);
    add_f32(prefix + "w_gate.weight", {cfg.d_ff, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "w_up.weight", {cfg.d_ff, cfg.d_model}, 0.25, 0.0);
    add_f32(prefix + "w_down.weight", {cfg.d_model, cfg.d_ff}, 0.25, 0.0);
  }
  add_f32("norm.weight", {cfg.d_model}, 0.25, 0.85);
  add_f32("lm_head.weight", {cfg.vocab_size, cfg.d_model}, 0.35, 0.0);

  std::map<std::string, std::string> meta;
  meta["architecture"] = "llama_micro";
  meta["vocab_size"] = std::to_string(cfg.vocab_size);
  meta["n_layers"] = std::to_string(cfg.n_layers);
  meta["d_model"] = std::to_string(cfg.d_model);
  meta["n_q_heads"] = std::to_string(cfg.n_q_heads);
  meta["n_kv_heads"] = std::to_string(cfg.n_kv_heads);
  meta["d_head"] = std::to_string(cfg.d_head);
  meta["d_ff"] = std::to_string(cfg.d_ff);
  meta["max_seq"] = std::to_string(cfg.max_seq);

  std::vector<uint8_t> blob;
  if (!serialize_safetensors_map(tensors, meta, &blob, err_out)) {
    return false;
  }

  std::ofstream ofs(path, std::ios::binary | std::ios::trunc);
  if (!ofs.is_open()) {
    *err_out = "failed to open output safetensors path: " + path;
    return false;
  }
  ofs.write(reinterpret_cast<const char*>(blob.data()),
            static_cast<std::streamsize>(blob.size()));
  if (!ofs.good()) {
    *err_out = "failed to write safetensors payload to: " + path;
    return false;
  }
  return true;
}

} // namespace aigpu::llm

#endif // AIGPU_LLM_SAFETENSORS_READER_H
