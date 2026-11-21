// SPDX-License-Identifier: Apache-2.0

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "runtime_loader.h"
#include "runtime.h"
#include "mlp_runtime.h"
#include "records.h"

#include <cstdint>
#include <chrono>
#include <cstring>
#include <exception>
#include <limits>
#include <memory>
#include <new>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <unistd.h>

namespace ai = vortex::ai;
namespace binding = vortex_ai_python;

namespace {

constexpr char kSessionCapsule[] = "vortex_ai._native.SessionOwner.v1";
constexpr char kOperationCapsule[] = "vortex_ai._native.MatmulOwner.v1";
constexpr char kModelCapsule[] = "vortex_ai._native.ModelOwner.v1";
constexpr uint64_t kMaximumWaitNs = 1000000000;
constexpr uint32_t kPoisons[] = {0x7fc0deadu, 0xdeadbeefu};
pid_t import_pid = 0;

// SimX finalizes process-wide simulator state when any device is destroyed.
struct NativeLease {};
std::weak_ptr<NativeLease> active_lease;
bool runtime_cleanup_failed = false;

bool acquire_lease(std::shared_ptr<NativeLease>* lease) {
  if (runtime_cleanup_failed) {
    PyErr_SetString(PyExc_BlockingIOError,
                    "native cleanup failed; start a fresh process before opening more work");
    return false;
  }
  if (!active_lease.expired()) {
    PyErr_SetString(PyExc_BlockingIOError,
                    "a native context is still active; close its operations and owner first");
    return false;
  }
  *lease = std::make_shared<NativeLease>();
  active_lease = *lease;
  return true;
}

void remember_cleanup(const ai::ExecutionResult& result) noexcept {
  if (result.cleanup != VX_SUCCESS) {
    runtime_cleanup_failed = true;
  }
}

template <typename NativeOwner>
void drain_owner(NativeOwner& native) noexcept {
  for (;;) {
    const auto result = native.close(VX_TIMEOUT_INFINITE);
    remember_cleanup(result);
    if (result.complete) {
      return;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}

struct Decref {
  void operator()(PyObject* object) const noexcept {
    Py_XDECREF(object);
  }
};

using PyOwned = std::unique_ptr<PyObject, Decref>;

struct OwnerContext {
  const pid_t pid = getpid();
  PyInterpreterState* const interpreter = PyInterpreterState_Get();
  bool busy = false;
};

struct SessionOwner : OwnerContext {
  binding::VerifiedBundle bundle;
  std::shared_ptr<NativeLease> lease;
  std::unique_ptr<ai::ManagedMatmul> native;
  ai::ExecutionResult last{};
  bool closing = false;
  bool closed = false;

  ~SessionOwner() {
    if (native) {
      remember_cleanup(native->close());
    }
  }
};

struct OperationOwner : OwnerContext {
  std::shared_ptr<NativeLease> lease;
  std::unique_ptr<ai::MatmulOperation> native;
  ai::ExecutionResult last{};
  size_t expected_words = 0;
  bool attempted = false;
  bool closed = false;

  ~OperationOwner() {
    if (native) {
      drain_owner(*native);
    }
  }
};

struct ModelOwner : OwnerContext {
  std::shared_ptr<NativeLease> lease;
  std::unique_ptr<ai::ManagedMlp> native;
  ai::MlpResult last{};
  std::string backend;
  std::string source_revision;
  std::string qualification_id;
  uint32_t poison = 0;
  bool attempted = false;
  bool closed = false;

  ~ModelOwner() {
    if (native) {
      drain_owner(*native);
    }
  }
};

class BusyGuard {
 public:
  explicit BusyGuard(OwnerContext* owner) : owner_(owner) {
    if (owner_->busy) {
      owner_ = nullptr;
      PyErr_SetString(PyExc_RuntimeError, "native owner is already in use");
    } else {
      owner_->busy = true;
    }
  }

  ~BusyGuard() {
    if (owner_) {
      owner_->busy = false;
    }
  }

  explicit operator bool() const noexcept { return owner_ != nullptr; }

 private:
  OwnerContext* owner_;
};

bool supported_context() {
#if PY_MAJOR_VERSION != 3 || PY_MINOR_VERSION != 12
  PyErr_SetString(PyExc_RuntimeError, "vortex_ai requires CPython 3.12");
  return false;
#elif defined(Py_GIL_DISABLED)
  PyErr_SetString(PyExc_RuntimeError, "vortex_ai does not support free-threaded Python");
  return false;
#else
  if (PyInterpreterState_Get() != PyInterpreterState_Main()) {
    PyErr_SetString(PyExc_RuntimeError, "vortex_ai requires the main Python interpreter");
    return false;
  }
  if (import_pid != 0 && import_pid != getpid()) {
    PyErr_SetString(PyExc_RuntimeError,
                    "vortex_ai cannot be used after fork; start a fresh process");
    return false;
  }
  return true;
#endif
}

PyObject* translate_exception() noexcept {
  try {
    throw;
  } catch (const std::bad_alloc&) {
    return PyErr_NoMemory();
  } catch (const std::exception& failure) {
    PyErr_SetString(PyExc_RuntimeError, failure.what());
  } catch (...) {
    PyErr_SetString(PyExc_RuntimeError, "unknown native binding exception");
  }
  return nullptr;
}

template <typename Function>
PyObject* boundary(Function&& function) noexcept {
  try {
    if (!supported_context() || PyErr_CheckSignals() < 0) {
      return nullptr;
    }
    PyOwned result(function());
    if (!result || PyErr_CheckSignals() < 0) {
      return nullptr;
    }
    return result.release();
  } catch (...) {
    return translate_exception();
  }
}

template <typename Owner>
Owner* get_owner(PyObject* capsule, const char* name) {
  if (!PyCapsule_CheckExact(capsule) || !PyCapsule_IsValid(capsule, name)) {
    PyErr_SetString(PyExc_TypeError, "expected the matching opaque vortex_ai handle");
    return nullptr;
  }
  auto* owner = static_cast<Owner*>(PyCapsule_GetPointer(capsule, name));
  if (!owner) {
    return nullptr;
  }
  if (owner->pid != getpid() || owner->interpreter != PyInterpreterState_Get()) {
    PyErr_SetString(PyExc_RuntimeError, "native handle belongs to another process or interpreter");
    return nullptr;
  }
  return owner;
}

template <typename Owner>
void destroy_capsule(PyObject* capsule, const char* name) noexcept {
  PyObject* saved = PyErr_GetRaisedException();
  try {
    auto* owner = static_cast<Owner*>(PyCapsule_GetPointer(capsule, name));
    if (owner) {
      if (owner->pid != getpid() || owner->interpreter != PyInterpreterState_Get()) {
        // The child's inherited runtime cannot safely wait or release parent work.
        owner->native.release();
      }
      delete owner;
    }
  } catch (...) {
    translate_exception();
  }
  if (PyErr_Occurred()) {
    PyErr_WriteUnraisable(capsule);
  }
  PyErr_SetRaisedException(saved);
}

void destroy_session(PyObject* capsule) noexcept {
  destroy_capsule<SessionOwner>(capsule, kSessionCapsule);
}

void destroy_operation(PyObject* capsule) noexcept {
  destroy_capsule<OperationOwner>(capsule, kOperationCapsule);
}

void destroy_model(PyObject* capsule) noexcept {
  destroy_capsule<ModelOwner>(capsule, kModelCapsule);
}

template <typename Owner>
PyObject* new_capsule(const char* name, PyCapsule_Destructor destructor) {
  auto owner = std::make_unique<Owner>();
  PyObject* capsule = PyCapsule_New(owner.get(), name, destructor);
  if (capsule) {
    owner.release();
  }
  return capsule;
}

bool set_item(PyObject* dictionary, const char* key, PyObject* value) {
  PyOwned owned(value);
  return owned && PyDict_SetItemString(dictionary, key, owned.get()) == 0;
}

PyObject* text(const std::string& value) {
  if (value.size() > static_cast<size_t>(PY_SSIZE_T_MAX)) {
    PyErr_SetString(PyExc_OverflowError, "native text is too large for Python");
    return nullptr;
  }
  return PyUnicode_DecodeUTF8(value.data(), static_cast<Py_ssize_t>(value.size()), "strict");
}

PyObject* execution_status(const ai::ExecutionResult& result) {
  PyOwned dictionary(PyDict_New());
  if (!dictionary
      || !set_item(dictionary.get(), "validation", PyUnicode_FromString(ai::status_string(result.validation)))
      || !set_item(dictionary.get(), "primary", PyLong_FromLong(static_cast<long>(result.primary)))
      || !set_item(dictionary.get(), "cleanup", PyLong_FromLong(static_cast<long>(result.cleanup)))
      || !set_item(dictionary.get(), "complete", PyBool_FromLong(result.complete))) {
    return nullptr;
  }
  return dictionary.release();
}

PyObject* model_status(const ai::MlpResult& result) {
  PyOwned dictionary(PyDict_New());
  if (!dictionary
      || !set_item(dictionary.get(), "status", PyUnicode_FromString(ai::mlp_status_string(result.status)))
      || !set_item(dictionary.get(), "execution", execution_status(result.execution))
      || !set_item(dictionary.get(), "terminal", PyBool_FromLong(result.terminal))) {
    return nullptr;
  }
  return dictionary.release();
}

bool unsigned_value(PyObject* object, const char* name, uint64_t maximum, uint64_t* value) {
  if (!PyLong_CheckExact(object)) {
    PyErr_Format(PyExc_TypeError, "%s must be an exact int, excluding bool", name);
    return false;
  }
  const auto converted = PyLong_AsUnsignedLongLong(object);
  if (PyErr_Occurred()) {
    return false;
  }
  if (converted > maximum) {
    PyErr_Format(PyExc_OverflowError, "%s exceeds its allowed range", name);
    return false;
  }
  *value = converted;
  return true;
}

bool word_value(PyObject* object, const char* name, uint32_t* value) {
  uint64_t converted = 0;
  if (!unsigned_value(object, name, std::numeric_limits<uint32_t>::max(), &converted)) {
    return false;
  }
  *value = static_cast<uint32_t>(converted);
  return true;
}

bool string_value(PyObject* object, const char* name, std::string* value) {
  if (!PyUnicode_CheckExact(object)) {
    PyErr_Format(PyExc_TypeError, "%s must be an exact str", name);
    return false;
  }
  Py_ssize_t size = 0;
  const char* data = PyUnicode_AsUTF8AndSize(object, &size);
  if (!data) {
    return false;
  }
  if (std::memchr(data, '\0', static_cast<size_t>(size))) {
    PyErr_Format(PyExc_ValueError, "%s cannot contain a NUL byte", name);
    return false;
  }
  value->assign(data, static_cast<size_t>(size));
  return true;
}

class InputBuffer {
 public:
  ~InputBuffer() {
    if (acquired_) {
      PyBuffer_Release(&view_);
    }
  }

  bool acquire(PyObject* exporter, size_t expected, const char* name) {
    if (PyObject_GetBuffer(exporter, &view_, PyBUF_FULL_RO) < 0) {
      return false;
    }
    acquired_ = true;
    if (view_.ndim != 1 || view_.itemsize != 1 || !view_.shape || !view_.strides
        || view_.strides[0] != 1 || !PyBuffer_IsContiguous(&view_, 'C')
        || (view_.suboffsets && view_.suboffsets[0] >= 0)
        || !view_.format || std::strlen(view_.format) != 1
        || (view_.format[0] != 'B' && view_.format[0] != 'b' && view_.format[0] != 'c')) {
      PyErr_Format(PyExc_ValueError, "%s must be contiguous rank-one byte storage", name);
      return false;
    }
    if (view_.len < 0 || static_cast<size_t>(view_.len) != expected
        || view_.shape[0] != view_.len || (expected != 0 && !view_.buf)) {
      PyErr_Format(PyExc_ValueError, "%s has an incorrect byte extent", name);
      return false;
    }
    return true;
  }

  const void* data() const noexcept { return view_.buf; }
  size_t size() const noexcept { return static_cast<size_t>(view_.len); }

 private:
  Py_buffer view_{};
  bool acquired_ = false;
};

bool supported_shape(uint32_t m, uint32_t n, uint32_t k) noexcept {
  return (m == 8 && n == 4 && (k == 8 || k == 16)) || (m == 16 && n == 8 && k == 16);
}

bool session_available(const SessionOwner& owner) {
  if (owner.closing || owner.closed) {
    PyErr_SetString(PyExc_BlockingIOError, "native session is closing or closed");
    return false;
  }
  if (runtime_cleanup_failed) {
    PyErr_SetString(PyExc_BlockingIOError,
                    "native cleanup failed; start a fresh process before submitting more work");
    return false;
  }
  return true;
}

ai::ExecutionBinding execution_binding(const binding::VerifiedBundle& bundle) {
  ai::ExecutionBinding result;
  result.profile = {ai::Profile::p02_tfr_wmma_v1, true, true};
  result.input_dtype = bundle.format == "fp16" ? ai::DType::fp16 : ai::DType::bf16;
  result.module_bytes = bundle.module_bytes.data();
  result.module_size = bundle.module_bytes.size();
  result.qualification_id = bundle.qualification_id;
  result.enable_profiling = true;
  return result;
}

bool resume_matmul(SessionOwner* owner) {
  if (owner->native) {
    return true;
  }
  if (!acquire_lease(&owner->lease)) {
    return false;
  }
  owner->last = ai::ManagedMatmul::create(execution_binding(owner->bundle), &owner->native);
  remember_cleanup(owner->last);
  if (!owner->native) {
    owner->lease.reset();
    owner->closing = true;
    owner->closed = owner->last.complete;
  }
  return true;
}

PyObject* word_bytes(const uint32_t* words, size_t count) {
  if (count > static_cast<size_t>(PY_SSIZE_T_MAX) / 4) {
    PyErr_SetString(PyExc_OverflowError, "native output is too large for Python");
    return nullptr;
  }
  PyOwned output(PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(count * 4)));
  if (!output) {
    return nullptr;
  }
  auto* data = reinterpret_cast<unsigned char*>(PyBytes_AS_STRING(output.get()));
  for (size_t i = 0; i != count; ++i) {
    for (unsigned byte = 0; byte != 4; ++byte) {
      data[i * 4 + byte] = static_cast<unsigned char>(words[i] >> (8 * byte));
    }
  }
  return output.release();
}

bool profiled(const ai::MlpTrace& trace) noexcept {
  for (const auto& stage : trace.native) {
    const auto& dispatch = stage.dispatch;
    if (!stage.submitted || !stage.waited || !stage.trace_valid || !stage.output_valid
        || !stage.compared || !stage.closed || !stage.submission.ok()
        || !stage.completion.ok() || !stage.completion.complete
        || !stage.cleanup.ok() || !stage.cleanup.complete || stage.mismatches != 0
        || !dispatch.profiling_enabled || dispatch.writes_enqueued != 3
        || dispatch.launches_enqueued != 1 || dispatch.reads_enqueued != 1
        || dispatch.wait_calls == 0) {
      return false;
    }
    for (size_t i = 0; i != dispatch.event_profiles.size(); ++i) {
      const auto& profile = dispatch.event_profiles[i];
      if (dispatch.event_results[i] != VX_SUCCESS || !dispatch.event_profile_queried[i]
          || dispatch.event_profile_results[i] != VX_SUCCESS
          || profile.queued_ns > profile.submit_ns || profile.submit_ns > profile.start_ns
          || profile.start_ns > profile.end_ns) {
        return false;
      }
    }
  }
  return true;
}

bool model_output_ready(const ai::MlpTrace& trace) noexcept {
  const auto& resources = trace.resources;
  return trace.result.ok() && trace.owner_closed && trace.owner_cleanup.ok()
      && trace.owner_cleanup.complete && trace.hidden_valid && trace.bridge_attempted
      && trace.bridge_valid && trace.bridge_compared && trace.assembled
      && trace.logits_valid && trace.logits_compared
      && trace.bridge_status == ai::BridgeStatus::success
      && trace.bridge_checked_words == trace.bridge_words.size() && trace.bridge_mismatches == 0
      && trace.output_checked_words == trace.output_words.size() && trace.output_mismatches == 0
      && resources.before_valid && resources.after_valid
      && resources.before_status == VX_SUCCESS && resources.after_status == VX_SUCCESS
      && resources.free_before == resources.free_after && resources.used_before == resources.used_after
      && profiled(trace);
}

PyObject* build_info(PyObject*, PyObject*) noexcept {
  return boundary([]() -> PyObject* {
    PyOwned result(PyDict_New());
    if (!result
        || !set_item(result.get(), "bundle_sha256", PyUnicode_FromString(binding::compiled_bundle_digest()))
        || !set_item(result.get(), "source_sha256", PyUnicode_FromString(binding::compiled_source_digest()))
        || !set_item(result.get(), "binding_api", PyLong_FromLong(1))) {
      return nullptr;
    }
    return result.release();
  });
}

PyObject* session_open(PyObject*, PyObject* root_object) noexcept {
  return boundary([&]() -> PyObject* {
    std::string root;
    if (!string_value(root_object, "bundle_root", &root)) {
      return nullptr;
    }
    PyOwned capsule(new_capsule<SessionOwner>(kSessionCapsule, destroy_session));
    if (!capsule) {
      return nullptr;
    }
    auto* owner = get_owner<SessionOwner>(capsule.get(), kSessionCapsule);
    if (!owner) {
      return nullptr;
    }
    std::string error;
    if (!binding::verify_bundle(root, &owner->bundle, &error)) {
      PyErr_SetString(PyExc_RuntimeError, error.c_str());
      return nullptr;
    }
    if (owner->bundle.format != "fp16" && owner->bundle.format != "bf16") {
      PyErr_SetString(PyExc_RuntimeError, "verified bundle has an unsupported input format");
      return nullptr;
    }
    if (!binding::load_runtime(owner->bundle.libraries, owner->bundle.backend, &error)) {
      PyErr_SetString(PyExc_RuntimeError, error.c_str());
      return nullptr;
    }
    if (!resume_matmul(owner)) {
      return nullptr;
    }
    PyOwned status(execution_status(owner->last));
    if (!status) {
      return nullptr;
    }
    if (!owner->last.ok() || !owner->last.complete || !owner->native) {
      return PyTuple_Pack(2, Py_None, status.get());
    }
    return PyTuple_Pack(2, capsule.get(), status.get());
  });
}

PyObject* session_info(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<SessionOwner>(capsule, kSessionCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    const auto& bundle = owner->bundle;
    PyOwned paths(PyTuple_New(static_cast<Py_ssize_t>(bundle.libraries.size())));
    if (!paths) {
      return nullptr;
    }
    for (size_t i = 0; i != bundle.libraries.size(); ++i) {
      PyObject* path = text(bundle.libraries[i]);
      if (!path) {
        return nullptr;
      }
      PyTuple_SET_ITEM(paths.get(), static_cast<Py_ssize_t>(i), path);
    }
    PyOwned result(PyDict_New());
    if (!result
        || !set_item(result.get(), "format", text(bundle.format))
        || !set_item(result.get(), "backend", text(bundle.backend))
        || !set_item(result.get(), "qualification_id", text(bundle.qualification_id))
        || !set_item(result.get(), "source_revision", text(bundle.source_revision))
        || !set_item(result.get(), "bundle_sha256", text(bundle.bundle_sha256))
        || !set_item(result.get(), "source_sha256", text(bundle.source_sha256))
        || !set_item(result.get(), "libraries", paths.release())) {
      return nullptr;
    }
    return result.release();
  });
}

PyObject* session_memory_info(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<SessionOwner>(capsule, kSessionCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    uint64_t free_bytes = 0;
    uint64_t used_bytes = 0;
    if (!session_available(*owner) || !resume_matmul(owner)) {
      return nullptr;
    }
    const auto code = owner->native
        ? owner->native->memory_info(&free_bytes, &used_bytes)
        : owner->last.primary != VX_SUCCESS ? owner->last.primary
        : owner->last.cleanup != VX_SUCCESS ? owner->last.cleanup : VX_ERR_INVALID_HANDLE;
    return Py_BuildValue("(iKK)", static_cast<int>(code),
                         static_cast<unsigned long long>(free_bytes),
                         static_cast<unsigned long long>(used_bytes));
  });
}

PyObject* session_close(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<SessionOwner>(capsule, kSessionCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    owner->closing = true;
    if (!owner->closed) {
      owner->last = owner->native ? owner->native->close() : ai::ExecutionResult{};
      owner->closed = owner->last.complete;
      remember_cleanup(owner->last);
      if (owner->closed) {
        owner->native.reset();
        owner->lease.reset();
      }
    }
    return execution_status(owner->last);
  });
}

PyObject* operation_new(PyObject*, PyObject*) noexcept {
  return boundary([]() -> PyObject* {
    return new_capsule<OperationOwner>(kOperationCapsule, destroy_operation);
  });
}

PyObject* submit_into(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* session_object;
    PyObject* operation_object;
    PyObject* m_object;
    PyObject* n_object;
    PyObject* k_object;
    PyObject* a_object;
    PyObject* b_object;
    PyObject* poison_object;
    if (!PyArg_ParseTuple(args, "OOOOOOOO:submit_into", &session_object, &operation_object,
                         &m_object, &n_object, &k_object, &a_object, &b_object, &poison_object)) {
      return nullptr;
    }
    auto* session = get_owner<SessionOwner>(session_object, kSessionCapsule);
    auto* operation = get_owner<OperationOwner>(operation_object, kOperationCapsule);
    if (!session || !operation) {
      return nullptr;
    }
    BusyGuard session_guard(session);
    BusyGuard operation_guard(operation);
    if (!session_guard || !operation_guard || !session_available(*session)) {
      return nullptr;
    }
    if (operation->attempted || operation->closed) {
      PyErr_SetString(PyExc_BlockingIOError, "operation handle can only be submitted once");
      return nullptr;
    }
    uint32_t m = 0;
    uint32_t n = 0;
    uint32_t k = 0;
    uint32_t poison = 0;
    if (!word_value(m_object, "m", &m) || !word_value(n_object, "n", &n)
        || !word_value(k_object, "k", &k) || !word_value(poison_object, "poison", &poison)) {
      return nullptr;
    }
    if (!supported_shape(m, n, k)) {
      operation->attempted = true;
      operation->last.validation = ai::Status::unsupported_shape;
      return execution_status(operation->last);
    }
    InputBuffer a;
    InputBuffer b;
    if (!a.acquire(a_object, static_cast<size_t>(m) * k * 2, "a_buffer")
        || !b.acquire(b_object, static_cast<size_t>(k) * n * 2, "b_buffer")) {
      return nullptr;
    }
    if (!resume_matmul(session)) {
      return nullptr;
    }
    // Different native queues do not share the launch-setup critical section.
    if (session->native && session->lease.use_count() != 1) {
      PyErr_SetString(PyExc_BlockingIOError,
                      "close the current matmul operation before submitting another");
      return nullptr;
    }
    operation->attempted = true;
    operation->expected_words = static_cast<size_t>(m) * n;
    if (!session->native) {
      operation->last = session->last;
      return execution_status(operation->last);
    }
    operation->lease = session->lease;
    operation->last = session->native->submit(m, n, k, a.data(), a.size(), b.data(), b.size(),
                                             poison, &operation->native);
    remember_cleanup(operation->last);
    if (!operation->native) {
      operation->lease.reset();
    }
    return execution_status(operation->last);
  });
}

PyObject* operation_wait(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* capsule;
    PyObject* timeout_object;
    if (!PyArg_ParseTuple(args, "OO:operation_wait", &capsule, &timeout_object)) {
      return nullptr;
    }
    auto* owner = get_owner<OperationOwner>(capsule, kOperationCapsule);
    uint64_t timeout = 0;
    if (!owner || !unsigned_value(timeout_object, "timeout_ns", kMaximumWaitNs, &timeout)) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->attempted && !owner->closed) {
      PyErr_SetString(PyExc_BlockingIOError, "operation has not been submitted");
      return nullptr;
    }
    if (owner->native && !owner->closed) {
      owner->last = owner->native->wait(timeout);
    }
    return execution_status(owner->last);
  });
}

PyObject* operation_close(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* capsule;
    PyObject* timeout_object;
    if (!PyArg_ParseTuple(args, "OO:operation_close", &capsule, &timeout_object)) {
      return nullptr;
    }
    auto* owner = get_owner<OperationOwner>(capsule, kOperationCapsule);
    uint64_t timeout = 0;
    if (!owner || !unsigned_value(timeout_object, "timeout_ns", kMaximumWaitNs, &timeout)) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->closed) {
      if (owner->native) {
        owner->last = owner->native->close(timeout);
      }
      owner->closed = owner->last.complete;
      remember_cleanup(owner->last);
      if (owner->closed) {
        owner->lease.reset();
      }
    }
    return execution_status(owner->last);
  });
}

PyObject* operation_output(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<OperationOwner>(capsule, kOperationCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->native || !owner->last.complete || !owner->last.ok()) {
      PyErr_SetString(PyExc_RuntimeError, "operation has no complete successful output");
      return nullptr;
    }
    const auto& words = owner->native->output_words();
    if (owner->expected_words == 0 || words.size() != owner->expected_words) {
      PyErr_SetString(PyExc_RuntimeError, "operation has no observed output with the expected extent");
      return nullptr;
    }
    return word_bytes(words.data(), words.size());
  });
}

PyObject* operation_trace(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<OperationOwner>(capsule, kOperationCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->native) {
      PyErr_SetString(PyExc_BlockingIOError, "operation has no native trace");
      return nullptr;
    }
    std::ostringstream output;
    output.exceptions(std::ios::badbit | std::ios::failbit);
    p04::records::dispatch(output, owner->native->trace());
    return text(output.str());
  });
}

PyObject* model_new(PyObject*, PyObject*) noexcept {
  return boundary([]() -> PyObject* {
    return new_capsule<ModelOwner>(kModelCapsule, destroy_model);
  });
}

PyObject* model_create_into(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* session_object;
    PyObject* model_object;
    PyObject* case_object;
    PyObject* poison_object;
    if (!PyArg_ParseTuple(args, "OOOO:model_create_into", &session_object, &model_object,
                         &case_object, &poison_object)) {
      return nullptr;
    }
    auto* session = get_owner<SessionOwner>(session_object, kSessionCapsule);
    auto* model = get_owner<ModelOwner>(model_object, kModelCapsule);
    if (!session || !model) {
      return nullptr;
    }
    BusyGuard session_guard(session);
    BusyGuard model_guard(model);
    if (!session_guard || !model_guard || !session_available(*session)) {
      return nullptr;
    }
    if (model->attempted || model->closed) {
      PyErr_SetString(PyExc_BlockingIOError, "model handle can only be created once");
      return nullptr;
    }
    std::string case_id;
    uint32_t poison = 0;
    if (!string_value(case_object, "case_id", &case_id)
        || !word_value(poison_object, "poison", &poison)) {
      return nullptr;
    }
    const auto* fixture = p04::find_case(case_id);
    if (!fixture) {
      PyErr_SetString(PyExc_ValueError, "case_id must name a compiled frozen model fixture");
      return nullptr;
    }
    if (session->bundle.format != fixture->format) {
      PyErr_SetString(PyExc_ValueError, "model fixture input format does not match the session");
      return nullptr;
    }
    const auto native_binding = execution_binding(session->bundle);
    ai::MlpCase input;
    input.case_id = fixture->id;
    input.input_dtype = native_binding.input_dtype;
    input.inputs.input_words = fixture->inputs.input_words;
    input.inputs.w1_words = fixture->inputs.w1_words;
    input.inputs.w2_words = fixture->inputs.w2_words;
    input.expected.hidden_words = fixture->expected.hidden_words;
    input.expected.bridge_words = fixture->expected.bridge_words;
    input.expected.output_words = fixture->expected.output_words;
    input.poison = poison;
    model->backend = session->bundle.backend;
    model->source_revision = session->bundle.source_revision;
    model->qualification_id = session->bundle.qualification_id;
    model->poison = poison;
    if (session->native) {
      session->last = session->native->close();
      remember_cleanup(session->last);
      if (!session->last.complete) {
        PyErr_SetString(PyExc_BlockingIOError,
                        "close all matmul operations before creating a model");
        return nullptr;
      }
      session->native.reset();
      session->lease.reset();
      if (!session->last.ok()) {
        session->closed = true;
        session->closing = true;
        model->attempted = true;
        model->last.execution = session->last;
        model->last.status = ai::MlpStatus::runtime_error;
        model->last.terminal = true;
        return execution_status(model->last.execution);
      }
    }
    if (!acquire_lease(&model->lease)) {
      return nullptr;
    }
    model->attempted = true;
    model->last.execution = ai::ManagedMlp::create(native_binding, input, &model->native);
    remember_cleanup(model->last.execution);
    if (!model->native) {
      model->lease.reset();
    }
    if (!model->last.execution.ok() || !model->last.execution.complete || !model->native) {
      model->last.status = ai::MlpStatus::runtime_error;
      model->last.terminal = true;
    }
    return execution_status(model->last.execution);
  });
}

PyObject* model_advance(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* capsule;
    PyObject* timeout_object;
    if (!PyArg_ParseTuple(args, "OO:model_advance", &capsule, &timeout_object)) {
      return nullptr;
    }
    auto* owner = get_owner<ModelOwner>(capsule, kModelCapsule);
    uint64_t timeout = 0;
    if (!owner || !unsigned_value(timeout_object, "timeout_ns", kMaximumWaitNs, &timeout)) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->attempted && !owner->closed) {
      PyErr_SetString(PyExc_BlockingIOError, "model has not been created");
      return nullptr;
    }
    if (owner->native && !owner->closed) {
      owner->last = owner->native->advance(timeout);
    }
    return model_status(owner->last);
  });
}

PyObject* model_close(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* capsule;
    PyObject* timeout_object;
    if (!PyArg_ParseTuple(args, "OO:model_close", &capsule, &timeout_object)) {
      return nullptr;
    }
    auto* owner = get_owner<ModelOwner>(capsule, kModelCapsule);
    uint64_t timeout = 0;
    if (!owner || !unsigned_value(timeout_object, "timeout_ns", kMaximumWaitNs, &timeout)) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->closed) {
      if (owner->native) {
        owner->last.execution = owner->native->close(timeout);
        owner->last = owner->native->trace().result;
      } else if (!owner->attempted) {
        owner->last.status = ai::MlpStatus::closed;
        owner->last.terminal = true;
      }
      owner->closed = owner->last.execution.complete;
      remember_cleanup(owner->last.execution);
      if (owner->closed) {
        owner->lease.reset();
      }
    }
    return execution_status(owner->last.execution);
  });
}

PyObject* model_trace(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<ModelOwner>(capsule, kModelCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->native) {
      PyErr_SetString(PyExc_BlockingIOError, "model has no native trace");
      return nullptr;
    }
    std::ostringstream output;
    output.exceptions(std::ios::badbit | std::ios::failbit);
    p04::records::trace(output, owner->native->trace());
    return text(output.str());
  });
}

PyObject* model_record(PyObject*, PyObject* args) noexcept {
  return boundary([&]() -> PyObject* {
    PyObject* capsule;
    PyObject* iteration_object;
    if (!PyArg_ParseTuple(args, "OO:model_record", &capsule, &iteration_object)) {
      return nullptr;
    }
    auto* owner = get_owner<ModelOwner>(capsule, kModelCapsule);
    uint64_t iteration = 0;
    if (!owner || !unsigned_value(iteration_object, "iteration", 1, &iteration)) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->native) {
      PyErr_SetString(PyExc_BlockingIOError, "model has no native execution record");
      return nullptr;
    }
    if (owner->poison != kPoisons[iteration]) {
      PyErr_SetString(PyExc_ValueError, "iteration does not match the model's output poison");
      return nullptr;
    }
    std::ostringstream output;
    output.exceptions(std::ios::badbit | std::ios::failbit);
    p04::write_result(output, owner->native->trace(), owner->backend,
                      owner->source_revision, owner->qualification_id,
                      static_cast<uint32_t>(iteration));
    return text(output.str());
  });
}

PyObject* model_output(PyObject*, PyObject* capsule) noexcept {
  return boundary([&]() -> PyObject* {
    auto* owner = get_owner<ModelOwner>(capsule, kModelCapsule);
    if (!owner) {
      return nullptr;
    }
    BusyGuard guard(owner);
    if (!guard) {
      return nullptr;
    }
    if (!owner->native || !owner->closed || !model_output_ready(owner->native->trace())) {
      PyErr_SetString(PyExc_RuntimeError,
                      "model output requires successful inference, close, profiling and resource checks");
      return nullptr;
    }
    const auto& words = owner->native->trace().output_words;
    return word_bytes(words.data(), words.size());
  });
}

PyObject* fixture_cases(PyObject*, PyObject*) noexcept {
  return boundary([]() -> PyObject* {
    PyOwned cases(PyTuple_New(static_cast<Py_ssize_t>(p04::kCaseCount)));
    if (!cases) {
      return nullptr;
    }
    for (size_t i = 0; i != p04::kCaseCount; ++i) {
      PyObject* name = PyUnicode_FromString(p04::kFixtures[i].id);
      if (!name) {
        return nullptr;
      }
      PyTuple_SET_ITEM(cases.get(), static_cast<Py_ssize_t>(i), name);
    }
    return cases.release();
  });
}

PyMethodDef methods[] = {
    {"build_info", build_info, METH_NOARGS, "Return immutable compiled bundle and source digests."},
    {"session_open", session_open, METH_O, "Verify a pinned bundle and create a managed session."},
    {"session_info", session_info, METH_O, "Copy verified session metadata."},
    {"session_memory_info", session_memory_info, METH_O, "Return runtime memory accounting and status."},
    {"session_close", session_close, METH_O, "Close the session owner without abandoning operations."},
    {"operation_new", operation_new, METH_NOARGS, "Allocate an empty managed operation handle."},
    {"submit_into", submit_into, METH_VARARGS, "Copy byte inputs and submit into a preallocated handle."},
    {"operation_wait", operation_wait, METH_VARARGS, "Wait with a bounded timeout while retaining ownership."},
    {"operation_close", operation_close, METH_VARARGS, "Drain and close an operation with a bounded timeout."},
    {"operation_output", operation_output, METH_O, "Copy completed successful output as little-endian FP32 bits."},
    {"operation_trace", operation_trace, METH_O, "Copy the native dispatch trace as JSON."},
    {"model_new", model_new, METH_NOARGS, "Allocate an empty fixed-model handle."},
    {"model_create_into", model_create_into, METH_VARARGS, "Create a fixed compiled fixture model owner."},
    {"model_advance", model_advance, METH_VARARGS, "Advance a model with a bounded timeout per native wait."},
    {"model_close", model_close, METH_VARARGS, "Stop graph advancement and drain the model owner."},
    {"model_trace", model_trace, METH_O, "Copy the native model trace as JSON."},
    {"model_record", model_record, METH_VARARGS, "Copy a native model record with its observed status."},
    {"model_output", model_output, METH_O, "Copy successfully closed model output as FP32 bits."},
    {"fixture_cases", fixture_cases, METH_NOARGS, "Return the exact compiled frozen case inventory."},
    {nullptr, nullptr, 0, nullptr}};

int module_exec(PyObject*) noexcept {
  try {
    if (!supported_context()) {
      return -1;
    }
    if (import_pid == 0) {
      import_pid = getpid();
    }
    return 0;
  } catch (...) {
    translate_exception();
    return -1;
  }
}

PyModuleDef_Slot slots[] = {
    {Py_mod_exec, reinterpret_cast<void*>(module_exec)},
    {Py_mod_multiple_interpreters, Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED},
    {0, nullptr}};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native",
    "Opaque copying owners for the qualified native AI runtime; calls retain the GIL.",
    0,
    methods,
    slots,
    nullptr,
    nullptr,
    nullptr};

} // namespace

PyMODINIT_FUNC PyInit__native() {
  try {
    return PyModuleDef_Init(&module);
  } catch (...) {
    return translate_exception();
  }
}
