// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>

#ifdef SIMX_CHECKED_COUNTERS
#if (SIMX_CHECKED_COUNTERS + 0) != 1
#error "SIMX_CHECKED_COUNTERS must be 1 when defined"
#endif

#include <exception>
#include <limits>
#include <type_traits>

namespace vortex {

class PerfCounterError final : public std::exception {
public:
  enum class Reason {
    Overflow,
    Underflow,
    NegativeOperand,
  };

  explicit PerfCounterError(Reason reason) noexcept : reason_(reason) {}

  Reason reason() const noexcept { return reason_; }

  const char* what() const noexcept override {
    switch (reason_) {
    case Reason::Overflow:
      return "SIMX_CHECKED_COUNTER_FAILURE: overflow";
    case Reason::Underflow:
      return "SIMX_CHECKED_COUNTER_FAILURE: underflow";
    case Reason::NegativeOperand:
      return "SIMX_CHECKED_COUNTER_FAILURE: negative operand";
    }
    return "SIMX_CHECKED_COUNTER_FAILURE: invalid reason";
  }

private:
  Reason reason_;
};

class PerfCounter {
public:
  constexpr PerfCounter() = default;

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  constexpr PerfCounter(T value) : value_(nonnegative(value)) {}

  constexpr operator uint64_t() const noexcept { return value_; }

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  PerfCounter& operator=(T value) {
    value_ = nonnegative(value);
    return *this;
  }

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  PerfCounter& operator+=(T delta) {
    return add(nonnegative(delta));
  }

  PerfCounter& operator+=(const PerfCounter& delta) {
    return add(delta.value_);
  }

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  PerfCounter& operator-=(T delta) {
    return subtract(nonnegative(delta));
  }

  PerfCounter& operator-=(const PerfCounter& delta) {
    return subtract(delta.value_);
  }

  PerfCounter& operator++() { return add(1); }

  PerfCounter operator++(int) {
    PerfCounter previous = *this;
    add(1);
    return previous;
  }

  PerfCounter& operator--() { return subtract(1); }

  PerfCounter operator--(int) {
    PerfCounter previous = *this;
    subtract(1);
    return previous;
  }

  // Aggregation must not convert operands before the overflow check.
  void operator+(const PerfCounter&) const = delete;
  void operator-(const PerfCounter&) const = delete;
  void operator-() const = delete;

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  void operator+(T) const = delete;

  template <typename T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
  void operator-(T) const = delete;

  template <typename T>
  friend std::enable_if_t<std::is_integral_v<T>, void>
  operator+(T, const PerfCounter&) = delete;

  template <typename T>
  friend std::enable_if_t<std::is_integral_v<T>, void>
  operator-(T, const PerfCounter&) = delete;

private:
  [[noreturn]] static void fail(PerfCounterError::Reason reason) {
    throw PerfCounterError(reason);
  }

  template <typename T>
  static constexpr uint64_t nonnegative(T value) {
    static_assert(sizeof(T) <= sizeof(uint64_t), "counter operand is wider than uint64_t");
    if constexpr (std::is_signed_v<T>) {
      if (value < 0) {
        fail(PerfCounterError::Reason::NegativeOperand);
      }
    }
    return static_cast<uint64_t>(value);
  }

  PerfCounter& add(uint64_t delta) {
    if (delta > std::numeric_limits<uint64_t>::max() - value_) {
      fail(PerfCounterError::Reason::Overflow);
    }
    value_ += delta;
    return *this;
  }

  PerfCounter& subtract(uint64_t delta) {
    if (delta > value_) {
      fail(PerfCounterError::Reason::Underflow);
    }
    value_ -= delta;
    return *this;
  }

  uint64_t value_ = 0;
};

static_assert(sizeof(PerfCounter) == sizeof(uint64_t));
static_assert(std::is_trivially_copyable_v<PerfCounter>);

} // namespace vortex

#else

namespace vortex {
using PerfCounter = uint64_t;
}

#endif
