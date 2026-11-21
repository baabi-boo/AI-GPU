"""Execute the exact README example with real Torch and scripted native owners."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent / "AI-GPU"
WORK = Path(__file__).resolve().parent
README = ROOT / "python/README.md"
MATRIX = ROOT / "docs/project/p05-torch-compatibility.md"


def identity(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw)}


def main():
    text = README.read_text()
    python_blocks = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)
    for index, block in enumerate(python_blocks):
        compile(block, "README-python-block-" + str(index), "exec")
    example = re.search(r"## Eager PyTorch example.*?```python\n(.*?)\n```", text, re.DOTALL).group(1)
    shell_blocks = re.findall(r"```sh\n(.*?)\n```", text, re.DOTALL)
    for index, block in enumerate(shell_blocks):
        subprocess.run(["bash", "-n"], input=block, text=True, check=True,
                       capture_output=True, timeout=5)
    links = []
    for document in (README, MATRIX):
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text()):
            if target.startswith(("https://", "http://")):
                continue
            destination = target.split("#", 1)[0]
            if destination:
                path = (document.parent / destination).resolve()
                assert path.exists(), (document, target)
                links.append({"document": str(document), "target": target})

    spec = importlib.util.spec_from_file_location(
        "w04_a4_native_fixture", ROOT / "ci/project/test_p05_python_api.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    sys.path.insert(0, str(ROOT / "python"))
    observations = []
    for dtype in ("fp16", "bf16"):
        native = fixture.NativeMock()
        native.format = dtype
        sys.modules["vortex_ai._native"] = native
        sys.argv = ["/host-only/torch_example.py", "/host-only/scripted-bundle"]
        namespace = {"__name__": "__main__"}
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exec(compile(example, "README-eager-example", "exec"), namespace)
        import torch
        assert str(torch.__version__) == "2.15.0+cpu"
        a, b = namespace["a"], namespace["b"]
        session, adapter = namespace["session"], namespace["adapter"]
        result, model = namespace["result"], namespace["model_result"]
        submissions = [row for row in native.calls if isinstance(row, tuple) and row[0] == "submit"]
        models = [row for row in native.calls if isinstance(row, tuple) and row[0] == "model_create"]
        assert len(submissions) == len(models) == 1
        assert a.stride() == (8, 1) and b.stride() == (1, 8)
        assert a.storage_offset() == b.storage_offset() == 0
        assert a.untyped_storage().nbytes() == 128
        assert b.untyped_storage().nbytes() == 64
        assert not session.pending_operations()
        assert adapter._closed
        assert session.close().ok
        assert result.untyped_storage().data_ptr() != model.untyped_storage().data_ptr()
        snapshots = [value.view(torch.int32).flatten().tolist() for value in (result, model)]
        observations.append({"format": dtype, "outcome": "pass", "operator_calls": 2,
                             "scripted_matmul_submissions": len(submissions),
                             "scripted_model_creations": len(models),
                             "a_strides": list(a.stride()), "b_strides": list(b.stride()),
                             "returned_shapes": [list(result.shape), list(model.shape)],
                             "returned_words_after_shutdown": snapshots,
                             "stdout": stdout.getvalue()})
    report = {"schema_version": 1, "outcome": "pass",
              "scope": "documentation example using actual PyTorch and scripted native owners",
              "acceptance_claimed": False, "native_execution": "not_run",
              "python_version": platform.python_version(), "torch_version": str(torch.__version__),
              "python_blocks_compiled": len(python_blocks),
              "shell_blocks_syntax_checked": len(shell_blocks),
              "existing_relative_links": len(links),
              "source_files": [identity(path) for path in (README, MATRIX,
                  ROOT / "python/vortex_ai/torch_ops.py", ROOT / "ci/project/test_p05_python_api.py")],
              "observations": observations}
    (WORK / "w04_a4-example-probe.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        "outcome", "scope", "native_execution", "python_version", "torch_version",
        "python_blocks_compiled", "shell_blocks_syntax_checked", "existing_relative_links")}))


if __name__ == "__main__":
    main()
