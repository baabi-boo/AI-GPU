from pathlib import Path
import difflib
import hashlib
import json

root=Path('/workspace/scratch/55f1fb23ad42')
work=root/'p05-torch-work'
repo=root/'AI-GPU'
out=work/'drafts/w03_a2'
out.mkdir(parents=True,exist_ok=True)
adapter=work/'drafts/torch_ops.py'
before=adapter.read_text()
after=before.replace('''        self._ready()
        try:
            with _REGISTRY_GATE:
''','''        self._ready()
        retained_adapter = self
        try:
            with _REGISTRY_GATE:
''',1)
after=after.replace('''                    if existing._session is session:
                        raise _api.BindingError("This native session already has a PyTorch adapter",
''','''                    if existing._session is session:
                        # A prior constructor may have registered successfully
                        # before interruption prevented assignment by its caller.
                        retained_adapter = existing
                        raise _api.BindingError("This native session already has a PyTorch adapter",
''',1)
after=after.replace('''        except BaseException as error:
            _retain_error(error, self)
            raise

    def _ready(self):
''','''        except BaseException as error:
            _retain_error(error, retained_adapter)
            raise

    def _ready(self):
''',1)
after=after.replace('''        with self._session._gate:
            self._session._ensure_open()
        if self._session.pending_operations():
''','''        with self._session._gate:
            self._session._ensure_open()
            if not self._session.info:
                raise _api.BindingError(
                    "Native session initialization did not finish; close the retained "
                    "session before opening a new qualified session",
                    session=self._session, kind="state")
        if self._session.pending_operations():
''',1)
assert before!=after
(out/'torch_ops.py').write_text(after)
(work/'w03_a2_adapter.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/python/vortex_ai/torch_ops.py',tofile='b/python/vortex_ai/torch_ops.py')))

host=work/'drafts/p05_torch_host_tests.py'
h_before=host.read_text()
newtests='''    def test_failed_session_initialization_rejected_before_attach(self):
        self.close_current()
        failures = (
            ("native_status", "session_open", {"return_value": (
                {"ops": [], "closed": False}, native_status(primary=6))}),
            ("identity_schema", "session_info", {"return_value": {"format": "fp16"}}),
            ("identity_interruption", "session_info", {
                "side_effect": KeyboardInterrupt("injected identity interruption")}),
            ("status_schema", "session_open", {"return_value": (
                {"ops": [], "closed": False}, {"primary": 6})}),
        )
        for name, method, fault in failures:
            with self.subTest(failure=name):
                with mock.patch.object(self.native, method, **fault):
                    try:
                        api.Session.open("/host-only/scripted-bundle")
                    except BaseException as error:
                        failed_session = error.session
                    else:
                        self.fail("scripted opening fault did not raise")
                attempted_adapter = None
                try:
                    with self.assertRaises(api.BindingError) as caught:
                        attempted_adapter = ops.TorchSession(failed_session)
                    self.assertIs(caught.exception.session, failed_session)
                    self.assertEqual(dict(failed_session.info), {})
                    self.assertFalse(failed_session.pending_operations())
                finally:
                    if attempted_adapter is not None:
                        attempted_adapter.close()
                    self.assertTrue(failed_session.close().ok)
        self.assertEqual(self.counts(), 0)

    def test_duplicate_attach_error_retains_existing_adapter(self):
        with self.assertRaises(api.BindingError) as caught:
            ops.TorchSession(self.session)
        self.assertIs(caught.exception.adapter, self.adapter)
        self.assertIs(caught.exception.session, self.session)
        self.assertIs(caught.exception.adapter.session, self.session)
        self.assertEqual(self.counts(), 0)

    def test_constructor_return_interruption_keeps_recoverable_adapter(self):
        self.adapter.close()
        previous_trace = sys.gettrace()
        def interrupt_return(frame, event, _arg):
            if frame.f_code is ops.TorchSession.__init__.__code__ and event == "return":
                raise KeyboardInterrupt("injected constructor return interruption")
            return interrupt_return
        try:
            sys.settrace(interrupt_return)
            with self.assertRaises(KeyboardInterrupt):
                ops.TorchSession(self.session)
        finally:
            sys.settrace(previous_trace)
        with self.assertRaises(api.BindingError) as caught:
            ops.TorchSession(self.session)
        recovered = caught.exception.adapter
        self.owners.append((self.session, recovered))
        self.assertIs(recovered.session, self.session)
        self.assertNotEqual(recovered.token, 0)
        self.assertFalse(recovered.pending_operations())
        recovered.close()
        replacement = ops.TorchSession(self.session)
        self.owners.append((self.session, replacement))
        self.assertNotEqual(replacement.token, recovered.token)
        output = replacement.matmul(*self.tensors()[:2])
        self.assert_output(output, replacement.last_operation, (8, 4))

'''
needle='    def test_repeated_matmul_model_matmul_closes_every_owner(self):\n'
assert h_before.count(needle)==1
h_after=h_before.replace(needle,newtests+needle)
(out/'p05_torch_host_tests.py').write_text(h_after)
(work/'w03_a2_tests.patch').write_text(''.join(difflib.unified_diff(h_before.splitlines(True),h_after.splitlines(True),fromfile='a/ci/project/p05_torch_host_tests.py',tofile='b/ci/project/p05_torch_host_tests.py')))
manifest={'adapter':{'before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_sha256':hashlib.sha256(after.encode()).hexdigest()},'host_tests':{'before_sha256':hashlib.sha256(h_before.encode()).hexdigest(),'after_sha256':hashlib.sha256(h_after.encode()).hexdigest()}}
(work/'w03_a2_patch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
