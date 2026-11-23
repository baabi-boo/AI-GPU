# SPDX-License-Identifier: Apache-2.0
"""Reject ambiguous or substituted inert dependency build declarations."""

import hashlib
import unittest
from unittest import mock

import p06_dependency_graph as graph
import p06_dependency_sources as sources


class DependencyGraphTests(unittest.TestCase):
    def test_upstream_trailing_continuation_preserves_archive_order(self):
        continuation = " " + chr(92) + "\n"
        makefile = continuation.join(("OBJS_PRIMITIVES =", "    third$(OBJ)",
                                      "    first$(OBJ)", "    second$(OBJ)", ""))
        makefile += "\nOBJS_SPECIALIZE = other$(OBJ)\n\n"
        self.assertEqual(graph._softfloat_objects(makefile, "PRIMITIVES", 3),
                         ["third", "first", "second"])

    def test_noncontinued_terminal_object_is_also_a_complete_logical_list(self):
        self.assertEqual(graph._softfloat_objects("OBJS_OTHERS = first$(OBJ) second$(OBJ)\n\n",
                                                  "OTHERS", 2), ["first", "second"])

    def test_repeated_make_declaration_cannot_hide_the_effective_list(self):
        text = "OBJS_OTHERS = first$(OBJ)\n\nOBJS_OTHERS = changed$(OBJ)\n\n"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            graph._softfloat_objects(text, "OTHERS", 1)

    def test_make_variables_commands_and_directory_substitution_are_not_expanded(self):
        for word in ("$(UNLISTED)", "$(shell touch marker)", "../replacement$(OBJ)",
                     "first.o", "first$(OBJ);touch-marker"):
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, "declaration changed"):
                graph._softfloat_objects("OBJS_OTHERS = " + word + "\n\n", "OTHERS", 1)

    def test_missing_and_added_make_objects_cannot_satisfy_selected_count(self):
        for count in (1, 3):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "declaration changed"):
                graph._softfloat_objects("OBJS_OTHERS = first$(OBJ) second$(OBJ)\n\n", "OTHERS", count)

    def test_ramulator_header_inputs_do_not_become_translation_units(self):
        text = "target_sources(ramulator-dram PRIVATE dram.h impl/HBM2.cpp lambdas/preq.h impl/DDR4-VRR.cpp)"
        self.assertEqual(graph._ramulator_sources(text, "ramulator-dram", 2),
                         ["impl/HBM2.cpp", "impl/DDR4-VRR.cpp"])

    def test_extra_target_source_declaration_is_rejected(self):
        text = "target_sources(ramulator-dram PRIVATE selected.cpp)\ntarget_sources(other PRIVATE injected.cpp)"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            graph._ramulator_sources(text, "ramulator-dram", 1)

    def test_generator_expressions_variables_and_traversal_are_not_evaluated(self):
        for word in ("${INJECTED}", "$<TARGET_OBJECTS:injected>", "../injected.cpp", "impl/./injected.cpp"):
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, "grammar changed"):
                graph._ramulator_sources("target_sources(ramulator-dram PRIVATE " + word + ")",
                                          "ramulator-dram", 1)

    def test_target_name_visibility_and_population_are_exact(self):
        for text in ("target_sources(other PRIVATE selected.cpp)",
                     "target_sources(ramulator-dram PUBLIC selected.cpp)",
                     "target_sources(ramulator-dram PRIVATE first.cpp second.cpp)"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                graph._ramulator_sources(text, "ramulator-dram", 1)

    def test_invalid_manifest_is_rejected_before_any_retained_source_read(self):
        callback = mock.Mock(side_effect=AssertionError("source must remain unread"))
        with self.assertRaises(sources.SourceError):
            graph.source_plan({}, callback)
        callback.assert_not_called()

    def test_recipe_body_is_bound_to_manifest_before_parsing(self):
        body = b"OBJS_PRIMITIVES = actual$(OBJ)\n\n"
        manifest = {"sources": [{"name": "softfloat", "files": [{
            "path": "build/Linux-x86_64-GCC/Makefile", "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}]}]}
        for changed in (body.replace(b"actual", b"forged"), body + b"\n", body.decode()):
            with self.subTest(changed=repr(changed)), mock.patch.object(sources, "validate_manifest"), \
                    self.assertRaisesRegex(ValueError, "locked build source bytes differ"):
                graph.source_plan(manifest, lambda component, name: changed)


if __name__ == "__main__":
    unittest.main()
