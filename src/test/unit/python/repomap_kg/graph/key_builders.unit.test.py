from __future__ import annotations

import unittest

from repomap_kg.graph.keys import (
    config_document_key,
    config_path_key,
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    document_column_key,
    document_file_key,
    document_latex_command_key,
    document_section_key,
    document_sheet_key,
    document_table_key,
    email_address_key,
    email_attachment_stub_key,
    email_mailbox_key,
    email_message_key,
    email_part_key,
    email_thread_hint_key,
    env_key,
    external_url_key,
    feed_author_key,
    feed_category_key,
    feed_channel_key,
    feed_document_key,
    feed_item_key,
    host_category_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_output_key,
    nix_package_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
    tool_key,
    warc_document_key,
    warc_record_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)


class GraphKeyBuildersUnitTests(unittest.TestCase):
    def test_builders_encode_reserved_segment_characters(self):
        self.assertEqual(tool_key("my tool"), "tool:my%20tool")
        self.assertEqual(env_key("PATH"), "env:PATH")
        self.assertEqual(
            host_category_key("package-management"),
            "host.category:package-management",
        )
        self.assertEqual(
            python_module_key("repomap_kg.cli"),
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(
            python_class_key("repomap_kg.cli", "CliError"),
            "python.class:repomap_kg.cli:CliError",
        )
        self.assertEqual(
            python_function_key("repomap_kg.cli", "main:debug"),
            "python.function:repomap_kg.cli:main%3Adebug",
        )
        self.assertEqual(
            python_method_key("repomap_kg.storage", "Record", "to_dict"),
            "python.method:repomap_kg.storage:Record:to_dict",
        )
        self.assertEqual(
            nix_app_key("repo-map", "aarch64-darwin", "tool#debug"),
            "nix.app:repo-map:aarch64-darwin:tool%23debug",
        )
        self.assertEqual(
            nix_package_key("repo-map", "aarch64-darwin", "default"),
            "nix.package:repo-map:aarch64-darwin:default",
        )
        self.assertEqual(
            nix_dev_shell_key("repo-map", "aarch64-darwin", "default"),
            "nix.devShell:repo-map:aarch64-darwin:default",
        )
        self.assertEqual(
            nix_check_key("repo-map", "aarch64-darwin", "unit"),
            "nix.check:repo-map:aarch64-darwin:unit",
        )
        self.assertEqual(
            nix_output_key("repo-map", "packages/aarch64-darwin/default"),
            "nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault",
        )
        self.assertEqual(
            doc_page_key("docs/adr/0008-markdown-documentation-graph-model.md"),
            "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
        )
        self.assertEqual(
            doc_section_key("README.md", "current-status"),
            "doc.section:file%3AREADME.md:current-status",
        )
        self.assertEqual(doc_adr_key("0008"), "doc.adr:0008")
        self.assertEqual(
            doc_skill_key("docs-only-change-hygiene"),
            "doc.skill:docs-only-change-hygiene",
        )
        self.assertEqual(
            external_url_key("https://example.com/docs#install"),
            "external.url:https%3A%2F%2Fexample.com%2Fdocs%23install",
        )
        self.assertEqual(
            config_document_key("mcp/repo-map/config.json"),
            "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
        )
        self.assertEqual(
            config_path_key(
                "mcp/repo-map/config.json",
                "/projects/repo-map/pg_database",
            ),
            (
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                "%2Fprojects%2Frepo-map%2Fpg_database"
            ),
        )
        self.assertEqual(
            css_document_key("tools/test/report/static/report.css"),
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
        )
        self.assertEqual(
            css_rule_key("tools/test/report/static/report.css", "/media:1/rule:1"),
            (
                "css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                "%2Fmedia%3A1%2Frule%3A1"
            ),
        )
        self.assertEqual(
            css_selector_key("tools/test/report/static/report.css", "/rule:1/selector:2"),
            (
                "css.selector:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                "%2Frule%3A1%2Fselector%3A2"
            ),
        )
        self.assertEqual(
            css_custom_property_key("tools/test/report/static/report.css", "--surface"),
            (
                "css.custom_property:"
                "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface"
            ),
        )
        self.assertEqual(
            html_document_key("site/index.html"),
            "html.document:file%3Asite%2Findex.html",
        )
        self.assertEqual(
            html_element_key("site/index.html", "/html/body/main/a[2]"),
            "html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
        )
        self.assertEqual(
            html_anchor_key("site/index.html", "intro"),
            "html.anchor:file%3Asite%2Findex.html:intro",
        )
        self.assertEqual(
            xml_document_key("src/main/resources/applicationContext.xml"),
            (
                "xml.document:"
                "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml"
            ),
        )
        self.assertEqual(
            xml_element_key("pom.xml", "/project/dependencies/dependency[2]"),
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency%5B2%5D",
        )
        self.assertEqual(
            xml_attribute_key("beans.xml", "/beans/bean", "class"),
            "xml.attribute:file%3Abeans.xml:%2Fbeans%2Fbean:class",
        )
        self.assertEqual(
            feed_document_key("feeds/rss.xml"),
            "feed.document:file%3Afeeds%2Frss.xml",
        )
        self.assertEqual(
            feed_channel_key(
                "feed.document:file%3Afeeds%2Frss.xml",
                "self:https://example.com/feed.xml",
            ),
            (
                "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:"
                "self%3Ahttps%3A%2F%2Fexample.com%2Ffeed.xml"
            ),
        )
        self.assertEqual(
            feed_item_key(
                "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:channel",
                "guid:item:1",
            ),
            (
                "feed.item:"
                "feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Achannel:"
                "guid%3Aitem%3A1"
            ),
        )
        self.assertEqual(
            feed_author_key(
                "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:channel",
                "fixture author",
            ),
            (
                "feed.author:"
                "feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Achannel:"
                "fixture%20author"
            ),
        )
        self.assertEqual(
            feed_category_key(
                "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:channel",
                "Release Notes",
            ),
            (
                "feed.category:"
                "feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Achannel:"
                "Release%20Notes"
            ),
        )
        self.assertEqual(
            warc_document_key("archives/example.warc"),
            "warc.document:file%3Aarchives%2Fexample.warc",
        )
        self.assertEqual(
            warc_record_key(
                "warc.document:file%3Aarchives%2Fexample.warc",
                "record:<urn:uuid:1>",
            ),
            (
                "warc.record:"
                "warc.document%3Afile%253Aarchives%252Fexample.warc:"
                "record%3A%3Curn%3Auuid%3A1%3E"
            ),
        )
        self.assertEqual(
            document_file_key("docs/notes.txt"),
            "document.file:file%3Adocs%2Fnotes.txt",
        )
        self.assertEqual(
            document_section_key("docs/notes.txt", "/sections/overview"),
            "document.section:file%3Adocs%2Fnotes.txt:%2Fsections%2Foverview",
        )
        self.assertEqual(
            document_table_key("data/report.csv", "/table"),
            "document.table:file%3Adata%2Freport.csv:%2Ftable",
        )
        self.assertEqual(
            document_sheet_key("spreadsheet.ods", "/sheets/budget"),
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
        )
        self.assertEqual(
            document_column_key("data/report.csv", "/table/columns/status"),
            (
                "document.column:file%3Adata%2Freport.csv:"
                "%2Ftable%2Fcolumns%2Fstatus"
            ),
        )
        self.assertEqual(
            document_latex_command_key("paper.tex", "/commands/input:1"),
            "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A1",
        )
        self.assertEqual(ruby_module_key("RepoMap"), "ruby.module:RepoMap")
        self.assertEqual(
            ruby_class_key("RepoMap::Runner"),
            "ruby.class:RepoMap%3A%3ARunner",
        )
        self.assertEqual(
            ruby_method_key("RepoMap::Runner", "call"),
            "ruby.method:RepoMap%3A%3ARunner:call",
        )
        self.assertEqual(
            ruby_file_key("lib/example.rb"),
            "ruby.file:file%3Alib%2Fexample.rb",
        )
        self.assertEqual(
            ruby_singleton_method_key("RepoMap::Runner", "build"),
            "ruby.singleton_method:RepoMap%3A%3ARunner:build",
        )
        self.assertEqual(
            ruby_constant_key("RepoMap::Runner", "DEFAULT_URL"),
            "ruby.constant:RepoMap%3A%3ARunner:DEFAULT_URL",
        )
        self.assertEqual(
            ruby_test_case_key("test/example_test.rb", "ExampleTest"),
            "ruby.test_case:file%3Atest%2Fexample_test.rb:ExampleTest",
        )
        self.assertEqual(
            ruby_test_method_key(
                "ruby.test_case:file%3Atest%2Fexample_test.rb:ExampleTest",
                "test_call",
            ),
            (
                "ruby.test_method:"
                "ruby.test_case%3Afile%253Atest%252Fexample_test.rb%3AExampleTest:"
                "test_call"
            ),
        )
        self.assertEqual(
            ruby_route_key("app.rb", "/routes/get:/health"),
            "ruby.route:file%3Aapp.rb:%2Froutes%2Fget%3A%2Fhealth",
        )
        self.assertEqual(
            email_mailbox_key("mail/sample.mbox"),
            "email.mailbox:file%3Amail%2Fsample.mbox",
        )
        self.assertEqual(
            email_message_key("mail/single-message.eml", "message:abc123"),
            "email.message:file%3Amail%2Fsingle-message.eml:message%3Aabc123",
        )
        self.assertEqual(
            email_address_key("addrhash:abc123"),
            "email.address:addrhash%3Aabc123",
        )
        self.assertEqual(
            email_part_key(
                "email.message:file%3Amail%2Fsingle-message.eml:message%3Aabc123",
                "/parts/1.2",
            ),
            (
                "email.part:"
                "email.message%3Afile%253Amail%252Fsingle-message.eml%3Amessage%253Aabc123:"
                "%2Fparts%2F1.2"
            ),
        )
        self.assertEqual(
            email_attachment_stub_key(
                "email.message:file%3Amail%2Fsingle-message.eml:message%3Aabc123",
                "/attachments/1",
            ),
            (
                "email.attachment_stub:"
                "email.message%3Afile%253Amail%252Fsingle-message.eml%3Amessage%253Aabc123:"
                "%2Fattachments%2F1"
            ),
        )
        self.assertEqual(
            email_thread_hint_key(
                "email.message:file%3Amail%2Fsingle-message.eml:message%3Aabc123",
                "/thread/in-reply-to/1",
            ),
            (
                "email.thread_hint:"
                "email.message%3Afile%253Amail%252Fsingle-message.eml%3Amessage%253Aabc123:"
                "%2Fthread%2Fin-reply-to%2F1"
            ),
        )


if __name__ == "__main__":
    unittest.main()
