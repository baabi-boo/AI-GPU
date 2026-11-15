# SPDX-License-Identifier: Apache-2.0
"""End-to-end Markdown visibility checks for project governance."""

import unittest

from test_check_project import IMAGE_PATH, ProjectFixture


ORIGINAL_EMBED = (
    '<p align="center">\n'
    f'  <img src="{IMAGE_PATH}" alt="Vortex framework stack" width="100%">\n'
    '</p>\n'
)
IMAGE_ERROR = f"README.md: protected image is not embedded: {IMAGE_PATH}"


class MarkdownEdgeTests(ProjectFixture):
    def readme_errors(self, content):
        self.write("README.md", content + "\n\n# Project\n")
        return self.project_errors()

    def guide_errors(self, content):
        self.write("docs/project/index.md", "# Guide\n\n" + content + "\n")
        return self.project_errors()

    def assert_reference_error(self, errors):
        self.assertTrue(any("undefined Markdown link reference" in error
                            for error in errors), errors)

    def assert_broken_link(self, errors):
        self.assertTrue(any("broken local link: missing.md" in error
                            for error in errors), errors)

    def test_original_html_embed_is_visible(self):
        self.assertEqual([], self.readme_errors(ORIGINAL_EMBED))

    def test_image_indentation_inside_original_html_block_is_visible(self):
        content = ORIGINAL_EMBED.replace("  <img", "    <img")
        self.assertEqual([], self.readme_errors(content))

    def test_even_backslashes_before_markdown_image_keep_it_visible(self):
        for count in (0, 2, 4):
            with self.subTest(backslashes=count):
                content = "\\" * count + f"![GPU]({IMAGE_PATH})"
                self.assertEqual([], self.readme_errors(content))

    def test_odd_backslashes_before_markdown_image_do_not_embed_it(self):
        for count in (1, 3):
            with self.subTest(backslashes=count):
                content = "\\" * count + f"![GPU]({IMAGE_PATH})"
                self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_escaped_image_label_bracket_does_not_embed_it(self):
        content = "!\\[GPU](" + IMAGE_PATH + ")"
        self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_even_backslashes_before_html_image_keep_it_visible(self):
        for count in (0, 2, 4):
            with self.subTest(backslashes=count):
                content = "\\" * count + f'<img src="{IMAGE_PATH}">'
                self.assertEqual([], self.readme_errors(content))

    def test_odd_backslashes_before_html_image_do_not_embed_it(self):
        for count in (1, 3):
            with self.subTest(backslashes=count):
                content = "\\" * count + f'<img src="{IMAGE_PATH}">'
                self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_escaped_html_tags_do_not_create_local_links(self):
        for count in (1, 3):
            for tag in ('<img src="missing.md">', '<a href="missing.md">Missing</a>'):
                with self.subTest(backslashes=count, tag=tag):
                    self.assertEqual([], self.guide_errors("\\" * count + tag))

    def test_even_backslashes_before_html_tags_keep_local_links_active(self):
        for count in (0, 2, 4):
            for tag in ('<img src="missing.md">', '<a href="missing.md">Missing</a>'):
                with self.subTest(backslashes=count, tag=tag):
                    self.assert_broken_link(self.guide_errors("\\" * count + tag))

    def test_reference_image_is_visible_with_a_defined_destination(self):
        content = f"![GPU][artwork]\n\n[artwork]: {IMAGE_PATH}\n"
        self.assertEqual([], self.readme_errors(content))

    def test_escaped_reference_image_marker_cannot_supply_an_embed(self):
        for count in (1, 3):
            with self.subTest(backslashes=count):
                content = "\\" * count + f"![GPU][artwork]\n\n[artwork]: {IMAGE_PATH}\n"
                self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_plain_link_to_image_does_not_supply_an_embed(self):
        self.assertIn(IMAGE_ERROR, self.readme_errors(f"[GPU]({IMAGE_PATH})"))

    def test_image_examples_inside_fences_or_inline_code_do_not_embed(self):
        for markup in (f"![GPU]({IMAGE_PATH})", f'<img src="{IMAGE_PATH}">'):
            for content in (f"`{markup}`", f"```markdown\n{markup}\n```",
                            f"~~~html\n{markup}\n~~~"):
                with self.subTest(content=content):
                    self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_odd_backslashes_before_undefined_reference_are_literal(self):
        for count in (1, 3):
            for suffix in ("[example][not-a-link]", "[example][]"):
                with self.subTest(backslashes=count, markup=suffix):
                    self.assertEqual([], self.guide_errors("\\" * count + suffix))

    def test_even_backslashes_before_undefined_reference_remain_active(self):
        for count in (0, 2, 4):
            for suffix in ("[example][not-a-link]", "[example][]"):
                with self.subTest(backslashes=count, markup=suffix):
                    self.assert_reference_error(self.guide_errors("\\" * count + suffix))

    def test_escaped_reference_suffix_is_not_an_active_full_reference(self):
        self.assertEqual([], self.guide_errors("[example]\\[not-a-link]"))

    def test_escaping_only_bang_keeps_undefined_link_reference_active(self):
        for prefix in ("!", "\\!", "\\\\!"):
            with self.subTest(prefix=prefix):
                self.assert_reference_error(self.guide_errors(prefix + "[example][missing]"))

    def test_escaped_image_bracket_does_not_form_a_full_reference(self):
        self.assertEqual([], self.guide_errors("!\\[example][not-a-link]"))

    def test_reference_in_code_is_ignored_but_active_peer_is_checked(self):
        content = "`[example][not-a-link]`\n\n~~~md\n[example][not-a-link]\n~~~"
        self.assertEqual([], self.guide_errors(content))
        self.assert_reference_error(self.guide_errors(content + "\n\n[example][not-a-link]"))

    def test_top_level_indented_images_do_not_supply_embed(self):
        for indent in ("    ", "\t"):
            for markup in (f"![GPU]({IMAGE_PATH})", f'<img src="{IMAGE_PATH}">'):
                with self.subTest(indent=repr(indent), markup=markup):
                    self.assertIn(IMAGE_ERROR, self.readme_errors(indent + markup))

    def test_top_level_indented_reference_image_does_not_supply_embed(self):
        content = f"    ![GPU][artwork]\n\n[artwork]: {IMAGE_PATH}\n"
        self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_top_level_indented_links_are_examples_not_live_targets(self):
        for indent in ("    ", "\t"):
            for markup in ("[Missing](missing.md)", "[Missing][not-a-link]",
                           '<a href="missing.md">Missing</a>', '<img src="missing.md">'):
                with self.subTest(indent=repr(indent), markup=markup):
                    self.assertEqual([], self.guide_errors(indent + markup))

    def test_active_link_after_indented_code_still_fails(self):
        content = "    [Example](absent-example.md)\n\n[Missing](missing.md)"
        errors = self.guide_errors(content)
        self.assert_broken_link(errors)
        self.assertFalse(any("absent-example.md" in error for error in errors), errors)

    def test_indented_paragraph_continuation_is_still_active(self):
        self.assert_broken_link(self.guide_errors("A paragraph continues\n    [Missing](missing.md)"))

    def test_indented_image_in_paragraph_continuation_is_visible(self):
        self.assertEqual([], self.readme_errors("Illustration:\n    ![GPU](" + IMAGE_PATH + ")"))

    def test_indented_code_cannot_supply_link_reference_definition(self):
        content = "[Purpose][contract]\n\n    [contract]: charter.md#purpose"
        self.assert_reference_error(self.guide_errors(content))

    def test_image_inside_list_continuation_is_visible(self):
        for indent in ("  ", "    "):
            with self.subTest(indent=len(indent)):
                content = "- Illustration\n\n" + indent + f"![GPU]({IMAGE_PATH})"
                self.assertEqual([], self.readme_errors(content))

    def test_active_links_in_list_continuations_remain_checked(self):
        for content in ("- Item\n\n  [Missing](missing.md)",
                        "- Item\n\n    [Missing](missing.md)",
                        "- Outer\n  - Inner\n\n    [Missing](missing.md)"):
            with self.subTest(content=content):
                self.assert_broken_link(self.guide_errors(content))

    def test_indented_code_within_list_is_not_active_markup(self):
        self.assertEqual([], self.guide_errors("- Example\n\n      [Missing](missing.md)"))
        content = "- Example\n\n      ![GPU](" + IMAGE_PATH + ")"
        self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_nested_list_code_is_not_active_markup(self):
        content = "- Outer\n  - Inner\n\n        [Missing](missing.md)"
        self.assertEqual([], self.guide_errors(content))

    def test_active_blockquote_image_is_visible(self):
        self.assertEqual([], self.readme_errors("> ![GPU](" + IMAGE_PATH + ")"))

    def test_active_blockquote_links_are_checked(self):
        for prefix in ("> ", "> > "):
            with self.subTest(prefix=prefix):
                self.assert_broken_link(self.guide_errors(prefix + "[Missing](missing.md)"))

    def test_blockquote_indented_code_cannot_supply_image(self):
        for prefix in (">     ", "> >     "):
            with self.subTest(prefix=prefix):
                content = prefix + "![GPU](" + IMAGE_PATH + ")"
                self.assertIn(IMAGE_ERROR, self.readme_errors(content))

    def test_blockquote_indented_code_links_are_ignored(self):
        for prefix in (">     ", "> >     "):
            with self.subTest(prefix=prefix):
                self.assertEqual([], self.guide_errors(prefix + "[Missing](missing.md)"))


if __name__ == "__main__":
    unittest.main()
