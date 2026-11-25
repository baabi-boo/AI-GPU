# SPDX-License-Identifier: Apache-2.0
"""Real SIGTERM controls at CLI handler installation, before execution starts."""

import os
import signal
import unittest
from unittest import mock

import p06_dependency_build as dependency
import p06_qualified_warm_execute as qualified_warm


class CliSignalSetupTests(unittest.TestCase):
    def interrupted_installation(self, module):
        install = signal.signal
        previous = signal.getsignal(signal.SIGTERM)
        sigint = signal.getsignal(signal.SIGINT)
        injections = []

        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run during CLI setup")

        def install_and_interrupt(number, handler):
            prior = install(number, handler)
            if not injections:
                injections.append(number)
                os.kill(os.getpid(), signal.SIGTERM)
            return prior

        install(signal.SIGTERM, enclosing)
        try:
            with mock.patch.object(module, "_main") as body, \
                    mock.patch.object(module.signal, "signal", side_effect=install_and_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    module.main([])
            body.assert_not_called()
            self.assertEqual(injections, [signal.SIGTERM])
            self.assertIs(signal.getsignal(signal.SIGINT), sigint)
            self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
        finally:
            install(signal.SIGTERM, previous)
            install(signal.SIGINT, sigint)

    def test_dependency_sigterm_during_install_restores_enclosing_handler(self):
        self.interrupted_installation(dependency)

    def test_qualified_warm_sigterm_during_install_restores_enclosing_handler(self):
        self.interrupted_installation(qualified_warm)


if __name__ == "__main__":
    unittest.main()
