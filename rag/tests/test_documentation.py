from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from offline_rag.bm25 import build_index, read_index_metadata, search
from offline_rag.documentation import (
    chunk_blocks,
    import_documentation,
    parse_asciidoc,
    parse_html,
    parse_go,
    parse_man,
    parse_markdown,
    parse_nginx_xml,
    parse_pod,
    parse_document,
    parse_docbook,
    parse_rfc,
    parse_rst,
)
from offline_rag.verify import verify_database


class DocumentationParserTests(unittest.TestCase):
    def test_go_extracts_package_docs_and_exported_declarations_without_bodies(self):
        parsed = parse_go(
            Path("go/src/net/http/server.go"),
            '''// Package http provides HTTP client and server implementations.
package http

// Server defines parameters for running an HTTP server.
type Server struct {
    // ReadTimeout limits reading the entire request.
    ReadTimeout time.Duration
}

// ListenAndServe listens on the TCP network address.
func (srv *Server) ListenAndServe() error {
    panic("implementation must not be indexed")
}

// AssemblyImplemented is implemented outside Go.
func AssemblyImplemented(value int) int

// SortFunc sorts a slice using a comparison function.
func SortFunc[S ~[]E, E any](values S, cmp func(a, b E) int) {
    panic("generic implementation must not be indexed")
}

// NextType must remain a separate declaration.
type NextType struct { Value int }

// Status codes returned by HTTP servers.
const (
    StatusOK = 200
    StatusNotFound = 404
)

func internalHelper() { panic("skip") }
''',
            "server",
        )
        self.assertEqual(parsed.title, "package net/http — server")
        self.assertEqual(parsed.format, "go")
        self.assertEqual(parsed.blocks[0].heading_path, ("package net/http",))
        self.assertIn("HTTP client and server", parsed.blocks[0].text)
        server = next(block for block in parsed.blocks if block.attributes.get("go_name") == "Server")
        self.assertIn("ReadTimeout", server.text)
        method = next(block for block in parsed.blocks if block.attributes.get("go_name") == "ListenAndServe")
        self.assertIn("TCP network address", method.text)
        self.assertNotIn("implementation must not be indexed", method.text)
        assembly = next(block for block in parsed.blocks if block.attributes.get("go_name") == "AssemblyImplemented")
        self.assertNotIn("NextType", assembly.text)
        generic = next(block for block in parsed.blocks if block.attributes.get("go_name") == "SortFunc")
        self.assertIn("S ~[]E", generic.text)
        self.assertNotIn("generic implementation must not be indexed", generic.text)
        constants = next(block for block in parsed.blocks if block.attributes.get("go_name") == "consts")
        self.assertIn("StatusNotFound", constants.text)
        self.assertFalse(any("internalHelper" in block.text for block in parsed.blocks))

    def test_go_language_html_has_canonical_title(self):
        parsed = parse_document(
            Path("go/doc/go_spec.html"),
            "<html><body><h2>Introduction</h2><p>This is the reference manual for Go.</p></body></html>",
        )
        self.assertEqual(parsed.title, "The Go Programming Language Specification")

    def test_binutils_bfd_html_replaces_upstream_untitled_title(self):
        parsed = parse_document(
            Path("bfd.html"),
            "<html><head><title>Untitled Document</title></head><body><h1>Top</h1><p>BFD targets.</p></body></html>",
        )
        self.assertEqual(parsed.title, "BFD Library")

    def test_html_preserves_title_hierarchy_code_and_tables(self):
        parsed = parse_html(
            """
            <html><head><title>Vector API</title><script>discard me</script></head><body>
            <nav>discard navigation</nav><div class="sphinxsidebar"><h3>Table of Contents</h3><p>discard sidebar</p></div>
            <h1>Containers<a href="#containers">¶</a></h1><p>Use <code>std::vector</code><br>carefully.</p>
            <h2>Example</h2><pre>std::vector&lt;int&gt; values;\nvalues.push_back(4);</pre>
            <table><tr><th>Error</th><th>Meaning</th></tr><tr><td>E23</td><td>Blocked intake</td></tr></table>
            </body></html>
            """,
            "fallback",
        )
        self.assertEqual(parsed.title, "Vector API")
        self.assertEqual(parsed.blocks[0].heading_path, ("Containers",))
        self.assertIn("std::vector", parsed.blocks[0].text)
        self.assertEqual(parsed.blocks[1].kind, "code")
        self.assertEqual(parsed.blocks[1].heading_path, ("Containers", "Example"))
        self.assertIn("values.push_back", parsed.blocks[1].text)
        self.assertTrue(any(block.text == "E23" and block.kind == "td" for block in parsed.blocks))
        self.assertFalse(any("discard" in block.text for block in parsed.blocks))

    def test_html_handles_generated_optional_end_tags_and_nosearch_navigation(self):
        parsed = parse_html(
            """
            <html><head><title>Write-Ahead Logging</title></head><body>
            <div class=nosearch><h2>Navigation</h2><p>discard table of contents</div>
            <h1 id=overview><span>1. </span>Overview</h1>
            <p>The rollback journal stores old database content.
            <p>The WAL stores new database content.</p>
            <p><dl><dt>Checkpoint</dt><dd>Transfers WAL content into the database.</dd></dl></p>
            <h2>Example</h2><blockquote><pre>PRAGMA journal_mode=WAL;</pre></blockquote>
            </body></html>
            """,
            "fallback",
        )
        texts = [block.text for block in parsed.blocks]
        self.assertEqual(parsed.title, "Write-Ahead Logging")
        self.assertIn("The rollback journal stores old database content.", texts)
        self.assertIn("The WAL stores new database content.", texts)
        self.assertIn("Checkpoint", texts)
        self.assertIn("Transfers WAL content into the database.", texts)
        self.assertIn("PRAGMA journal_mode=WAL;", texts)
        self.assertFalse(any("discard" in text for text in texts))
        self.assertEqual(parsed.blocks[-1].heading_path, ("1. Overview", "Example"))

    def test_apache_compound_html_ignores_generated_navigation(self):
        parsed = parse_document(
            Path("mod_proxy.html.en"),
            """<html><head><title>mod_proxy</title></head><body>
            <div id="page-header"><p>Apache navigation</p></div>
            <div id="path"><p>Documentation breadcrumb</p></div>
            <div class="toplang"><p>Available languages</p></div>
            <div id="page-content"><h1>Apache Module mod_proxy</h1>
            <p>Implements reverse proxy and load balancing.</p></div>
            <div id="quickview"><p>Topics navigation</p></div>
            </body></html>""",
        )
        self.assertEqual(parsed.format, "html")
        self.assertEqual(parsed.title, "mod_proxy")
        self.assertTrue(any("reverse proxy" in block.text for block in parsed.blocks))
        self.assertFalse(any("navigation" in block.text or "languages" in block.text for block in parsed.blocks))

    def test_rustdoc_html_removes_copy_and_anchor_controls(self):
        parsed = parse_html(
            '''<html><head><title>Pin in std::pin - Rust</title></head><body>
            <dialog><h2>Keyboard shortcuts</h2><p>Press S to search.</p></dialog>
            <h1>Struct <span>Pin</span><button id="copy-path">Copy item path</button></h1>
            <p>A pointer which pins its pointee in place.</p>
            <h2 class="section-header">Implementations<a class="anchor">§</a></h2>
            <p>Pinning prevents moves.</p>
            </body></html>''',
            "fallback",
        )
        self.assertEqual(parsed.blocks[0].heading_path, ("Struct Pin",))
        self.assertEqual(parsed.blocks[-1].heading_path, ("Struct Pin", "Implementations"))
        self.assertFalse(any("Copy item path" in block.text for block in parsed.blocks))
        self.assertFalse(any("Keyboard shortcuts" in block.text for block in parsed.blocks))

    def test_markdown_rst_and_man_structure(self):
        pandoc_manual = parse_markdown(
            "% podman-container-restore 1\n\n## NAME\npodman-container-restore - Restore containers.\n",
            "fallback",
        )
        self.assertEqual(pandoc_manual.title, "podman-container-restore")
        self.assertEqual(pandoc_manual.blocks[0].heading_path, ("NAME",))
        self.assertFalse(any(block.text.startswith("% ") for block in pandoc_manual.blocks))
        generated_manual = parse_document(
            Path("podman-run.1.md.in"),
            "% podman-run 1\n\n## NAME\npodman-run - Run a container.\n",
        )
        self.assertEqual(generated_manual.format, "markdown")
        self.assertEqual(generated_manual.title, "podman-run")

        markdown = parse_markdown(
            """# Build Guide

Introduction.

## Configure

```powershell
cmake --preset windows
```
""",
            "fallback",
        )
        self.assertEqual(markdown.title, "Build Guide")
        self.assertEqual(markdown.blocks[-1].heading_path, ("Build Guide", "Configure"))
        self.assertEqual(markdown.blocks[-1].attributes["language"], "powershell")

        rst = parse_rst(
            """SQLite Backup
=============

Create a consistent backup.

Example
-------

.. code-block:: sql

   VACUUM INTO 'backup.db';
""",
            "fallback",
        )
        self.assertEqual(rst.title, "SQLite Backup")
        self.assertEqual(rst.blocks[-1].kind, "code")
        self.assertEqual(rst.blocks[-1].attributes["language"], "sql")

        man = parse_man(
            '.TH OPEN 2 "2026-08-19" "Linux"\n.SH NAME\nopen \\- open a file\n.SH ERRORS\n.B EACCES\nPermission denied.\n',
            "open",
        )
        self.assertEqual(man.title, "OPEN")
        self.assertEqual(man.blocks[-1].heading_path, ("ERRORS",))
        self.assertIn("Permission denied", man.blocks[-1].text)

        mdoc = parse_man(
            '.Dd August 20, 2026\n.Dt SSHD_CONFIG 5\n.Sh AUTHENTICATION\n.It Cm PubkeyAuthentication\n'
            'Specifies whether public key authentication is allowed.\n.It Cm AuthorizedKeysFile\n'
            'Specifies the files containing public keys.\n',
            "sshd_config",
        )
        self.assertEqual(mdoc.title, "SSHD_CONFIG")
        self.assertEqual(mdoc.blocks[0].heading_path, ("AUTHENTICATION",))
        self.assertIn("PubkeyAuthentication", mdoc.blocks[0].text)
        self.assertIn("AuthorizedKeysFile", mdoc.blocks[1].text)

        frontmatter = parse_markdown(
            """---
title: Credentials
SPDX-License-Identifier: LGPL-2.1-or-later
---

# System and Service Credentials

<!-- YAML
added: v1.0.0
-->
<!-- source_link=lib/example.js -->
{{< tabs >}}
{{< /tabs >}}

Load credentials without environment variables.

```yaml
uses: action@{{% param "action_version" %}}
```
""",
            "fallback",
        )
        self.assertEqual(frontmatter.title, "Credentials")
        self.assertFalse(any("SPDX" in block.text for block in frontmatter.blocks))
        self.assertFalse(any("source_link" in block.text or "added:" in block.text for block in frontmatter.blocks))
        self.assertFalse(any("{{< tabs" in block.text for block in frontmatter.blocks))
        self.assertTrue(any("action_version" in block.text for block in frontmatter.blocks if block.kind == "code"))
        self.assertEqual(frontmatter.blocks[0].heading_path, ("System and Service Credentials",))

        mdn = parse_markdown(
            '''---
title: Array.fromAsync()
---

{{PreviousNext("Web/JavaScript/Reference", "Web/JavaScript/Guide")}}
{{SeeCompatTable}}

The {{jsxref("Array")}} method consumes an {{jsxref("AsyncIterator")}}.
''',
            "fallback",
        )
        mdn_text = "\n".join(block.text for block in mdn.blocks)
        self.assertIn("The Array method consumes an AsyncIterator", mdn_text)
        self.assertNotIn("PreviousNext", mdn_text)
        self.assertNotIn("SeeCompatTable", mdn_text)

        kubernetes = parse_markdown(
            '''---
title: Probes
---

{{< comment >}}
This template-only note must not be indexed.
{{< /comment >}}

The {{< glossary_tooltip
text="kubelet" term_id="kubelet" >}} runs probes.

{{< note >}}
Readiness failures remove a Pod from Service endpoints.
{{< /note >}}

## Configure probes {#configure-probes}

{{% heading "whatsnext" %}}

See {{< link text="Services" url="/docs/concepts/services-networking/service/" >}}.
''',
            "fallback",
        )
        kubernetes_text = "\n".join(block.text for block in kubernetes.blocks)
        self.assertIn("The kubelet runs probes", kubernetes_text)
        self.assertIn("Readiness failures", kubernetes_text)
        self.assertIn("See Services", kubernetes_text)
        self.assertNotIn("template-only", kubernetes_text)
        self.assertNotIn("{{", kubernetes_text)
        self.assertTrue(any(block.heading_path[-1:] == ("What's next",) for block in kubernetes.blocks))
        self.assertFalse(any("{#" in heading for block in kubernetes.blocks for heading in block.heading_path))

        asciidoc = parse_asciidoc(
            """= Git Manual

== Plumbing

[source,sh]
----
git cat-file -p HEAD
----
""",
            "fallback",
        )
        self.assertEqual(asciidoc.title, "Git Manual")
        self.assertEqual(asciidoc.blocks[-1].heading_path, ("Plumbing",))
        self.assertEqual(asciidoc.blocks[-1].attributes["language"], "sh")

        classic_asciidoc = parse_asciidoc(
            """git-rebase(1)
=============

NAME
----
git-rebase - Reapply commits.

DESCRIPTION
-----------
Transplant commits onto another base.
""",
            "fallback",
        )
        self.assertEqual(classic_asciidoc.title, "git-rebase(1)")
        self.assertEqual(classic_asciidoc.blocks[0].heading_path, ("NAME",))
        self.assertEqual(classic_asciidoc.blocks[-1].heading_path, ("DESCRIPTION",))

        diagram = parse_asciidoc(
            """= Layout

== Example

------------
/path/to/worktree 1234abc (detached HEAD)
------------
""",
            "fallback",
        )
        self.assertEqual(diagram.blocks[-1].kind, "code")
        self.assertEqual(diagram.blocks[-1].heading_path, ("Example",))

    def test_perl_pod_preserves_open_ssl_manual_structure_and_code(self):
        parsed = parse_pod(
            """=pod

=head1 NAME

openssl-verify - certificate verification utility

=head1 SYNOPSIS

 B<openssl verify> [B<-CAfile> I<file>] I<certificate.pem>

=head1 DESCRIPTION

The B<verify> command verifies certificate chains. See L<openssl-verification-options(1)>.

=over 4

=item B<-CAfile> I<file>

Load trusted certificates from C<file>.

=back

=cut
""",
            "verify",
        )
        self.assertEqual(parsed.title, "openssl-verify")
        self.assertEqual(parsed.format, "pod")
        self.assertTrue(any(block.kind == "code" and "openssl verify" in block.text for block in parsed.blocks))
        self.assertTrue(any(block.heading_path == ("DESCRIPTION",) for block in parsed.blocks))
        self.assertTrue(any("openssl-verification-options(1)" in block.text for block in parsed.blocks))
        templated = parse_document(Path("openssl-s_client.pod.in"), "=head1 NAME\n\nopenssl-s_client - TLS client\n")
        self.assertEqual(templated.format, "pod")
        self.assertEqual(templated.title, "openssl-s_client")

    def test_docbook_preserves_manual_sections_definitions_tables_and_local_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "standard-options.xml"
            helper.write_text(
                '<variablelist xmlns:xml="http://www.w3.org/XML/1998/namespace">'
                '<varlistentry xml:id="no-pager"><term><option>--no-pager</option></term>'
                '<listitem><para>Do not pipe output into a pager.</para></listitem></varlistentry>'
                '</variablelist>',
                encoding="utf-8",
            )
            source = root / "systemd-demo.xml"
            text = """<?xml version='1.0'?>
<!DOCTYPE refentry PUBLIC "-//OASIS//DTD DocBook XML V4.5//EN" "http://example.invalid/docbook.dtd">
<refentry xmlns:xi="http://www.w3.org/2001/XInclude">
  <refmeta><refentrytitle>systemd-demo</refentrytitle><manvolnum>1</manvolnum></refmeta>
  <refnamediv><refname>systemd-demo</refname><refpurpose>Demonstrate DocBook parsing</refpurpose></refnamediv>
  <refsect1><title>Options</title><variablelist>
    <varlistentry><term><varname>Restart=</varname></term><listitem><para>Restart after &DEFAULT_TIMEOUT_SEC;.</para></listitem></varlistentry>
    <xi:include href="standard-options.xml" xpointer="no-pager"/>
  </variablelist></refsect1>
  <refsect1><title>Example</title><programlisting>systemctl restart demo.service</programlisting>
  <table><title>States</title><tgroup><tbody><row><entry>active</entry><entry>running</entry></row></tbody></tgroup></table></refsect1>
</refentry>"""
            source.write_text(text, encoding="utf-8")
            parsed = parse_docbook(text, "fallback", source)
        self.assertEqual(parsed.title, "systemd-demo")
        self.assertEqual(parsed.format, "docbook")
        self.assertTrue(any(block.heading_path == ("NAME",) for block in parsed.blocks))
        self.assertTrue(any("Restart=" in block.text and "DEFAULT_TIMEOUT_SEC" in block.text for block in parsed.blocks))
        self.assertTrue(any("--no-pager" in block.text and "pager" in block.text for block in parsed.blocks))
        self.assertTrue(any(block.kind == "code" and "systemctl restart" in block.text for block in parsed.blocks))
        self.assertTrue(any(block.kind == "table_row" and "active | running" in block.text for block in parsed.blocks))

    def test_nginx_xml_preserves_directive_metadata_sections_code_and_entities(self):
        text = """<?xml version='1.0'?>
<!DOCTYPE module SYSTEM 'module.dtd'>
<module name='Module ngx_http_demo_module' link='/en/docs/http/ngx_http_demo_module.html' rev='3'>
  <section id='directives' name='Directives'>
    <directive name='demo_pass'>
      <syntax><value>URL</value> | <literal>off</literal></syntax>
      <default><literal>off</literal></default>
      <context>http</context><context>server</context><appeared-in>1.2.3</appeared-in>
      <para>Passes requests to an upstream&mdash;see <link id='upstream'/>.
        <example>demo_pass http://backend;</example></para>
    </directive>
  </section>
</module>"""
        parsed = parse_nginx_xml(text, "fallback")
        self.assertEqual(parsed.title, "Module ngx_http_demo_module")
        self.assertEqual(parsed.format, "nginx-xml")
        definition = next(block for block in parsed.blocks if block.kind == "definition")
        self.assertEqual(definition.heading_path, ("Directives", "demo_pass"))
        self.assertIn("Context: http, server", definition.text)
        self.assertIn("Appeared in: 1.2.3", definition.text)
        self.assertTrue(any("upstream—see upstream" in block.text for block in parsed.blocks))
        self.assertTrue(any(block.kind == "code" and "demo_pass" in block.text for block in parsed.blocks))

    def test_oversized_content_and_short_trailing_chunks(self):
        from offline_rag.documentation import ContentBlock

        blocks = (
            ContentBlock(("Large",), "word " * 90, "paragraph", {}),
            ContentBlock(("Large",), "short tail", "paragraph", {}),
        )
        chunks = chunk_blocks(blocks, max_chars=128, min_chars=40)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(text) <= 128 for _, text, _ in chunks))
        self.assertFalse(chunks[-1][1] == "short tail")

    def test_rfc_text_preserves_numbered_hierarchy(self):
        parsed = parse_rfc(
            """Network Working Group                                      A. Author
Request for Comments: 9999                                  August 2026

                    A Test Transport Protocol

1.  Introduction

This document defines a test protocol.

2.  Operation

2.1.  Handshake

The client sends HELLO before DATA.

Author [Page 1]
""",
            "rfc9999",
        )
        self.assertEqual(parsed.title, "A Test Transport Protocol")
        self.assertEqual(parsed.format, "rfc-text")
        self.assertEqual(parsed.blocks[-1].heading_path, ("2. Operation", "2.1. Handshake"))
        self.assertIn("HELLO", parsed.blocks[-1].text)
        self.assertFalse(any("Page 1" in block.text for block in parsed.blocks))

    def test_rfc_title_and_headings_handle_modern_and_early_formats(self):
        modern = parse_rfc(
            """Internet Engineering Task Force                         J. Example
Request for Comments: 9293                                  August 2022
STD: 7

                  Transmission Control Protocol (TCP)

Abstract

This document specifies TCP and updates prior requirements 1011 and 1122.

1.  Introduction

TCP provides a reliable byte stream.

Appendix A.  Other Changes

This appendix records changes.
""",
            "rfc9293",
        )
        self.assertEqual(modern.title, "Transmission Control Protocol (TCP)")
        self.assertIn(("Abstract",), [block.heading_path for block in modern.blocks])
        self.assertIn(("1. Introduction",), [block.heading_path for block in modern.blocks])
        self.assertIn(("Appendix A. Other Changes",), [block.heading_path for block in modern.blocks])
        self.assertFalse(any("1011. and" in " / ".join(block.heading_path) for block in modern.blocks))

        early = parse_rfc(
            """Network Working Group                                  Steve Crocker
Request for Comments: 1                                    UCLA
7 April 1969

Title: Host Software
Author: Steve Crocker

I. INTRODUCTION

The software is described here.
""",
            "rfc1",
        )
        self.assertEqual(early.title, "Host Software")
        self.assertFalse(any(path and path[-1].startswith("7.") for path in (block.heading_path for block in early.blocks)))


class DocumentationImportTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "guide.html").write_text(
            "<title>SQLite Recovery</title><h1>Recovery</h1>"
            "<p>Use the integrity_check pragma before attempting recovery.</p>"
            "<h2>Backup</h2><pre>VACUUM INTO 'backup.db';</pre>",
            encoding="utf-8",
        )
        (source / "api.md").write_text(
            "# C++ API\n\nThe foo_bar function returns a std::vector value.\n",
            encoding="utf-8",
        )
        (source / "search.html").write_text("<p>duplicate search index</p>", encoding="utf-8")
        (source / "asset.png").write_bytes(b"not documentation")
        return source

    def test_import_common_records_manifest_and_bm25_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            output = root / "processed"
            result = import_documentation(
                source,
                output,
                corpus="sqlite-docs",
                source_version="3.50.4",
                license_name="SQLite documentation terms",
                base_url="https://sqlite.org/docs/",
                source_timestamp="2026-08-19T00:00:00Z",
                max_chars=256,
                min_chars=30,
            )
            self.assertEqual(result["documents"], 2)
            manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
            stats = json.loads((output / "extraction-stats.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["record_format"], "offline-rag-common-jsonl-v1")
            self.assertTrue(stats["completed"])
            self.assertEqual(stats["stop_reason"], "source_complete")
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text().splitlines()]
            self.assertTrue(all(item["schema_version"] == 1 for item in documents + chunks))
            self.assertTrue(all(item["content_id"].startswith("sha256:") for item in chunks))
            recovery_chunks = [item for item in chunks if item["document_id"] == documents[1]["document_id"]]
            self.assertGreaterEqual(len(recovery_chunks), 2)
            self.assertEqual(recovery_chunks[0]["next_chunk_id"], recovery_chunks[1]["chunk_instance_id"])

            database = root / "docs.sqlite3"
            built = build_index(output, database)
            self.assertEqual(built["documents"], 2)
            metadata = read_index_metadata(database)
            self.assertEqual(metadata["source_corpora"], ["sqlite-docs"])
            result = search(database, "integrity_check pragma", limit=3)[0]
            self.assertEqual(result["title"], "SQLite Recovery")
            self.assertEqual(result["source_version"], "3.50.4")
            self.assertEqual(result["source_timestamp"], "2026-08-19T00:00:00Z")
            self.assertIn("sqlite-docs — SQLite Recovery § Recovery (3.50.4)", result["citation"])
            technical = search(database, "foo_bar std::vector C++", limit=3)[0]
            self.assertEqual(technical["title"], "C++ API")
            verification = verify_database(database, output, smoke_queries=("integrity_check pragma",))
            self.assertTrue(verification["verified"])

    def test_mdx_files_are_imported_as_structured_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "routing.mdx").write_text(
                "# Framework Routing\n\nUse nested layouts for shared user interface.\n",
                encoding="utf-8",
            )
            output = root / "processed"
            result = import_documentation(
                source,
                output,
                corpus="framework-docs",
                source_version="commit-1",
                license_name="CC-BY-4.0",
            )
            self.assertEqual(result["documents"], 1)
            document = json.loads((output / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(document["title"], "Framework Routing")
            self.assertEqual(document["attributes"]["format"], "markdown")

    def test_file_limit_is_explicitly_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            output = root / "limited"
            import_documentation(
                source,
                output,
                corpus="test-docs",
                source_version="1",
                license_name="test",
                max_files=1,
            )
            stats = json.loads((output / "extraction-stats.json").read_text())
            self.assertFalse(stats["completed"])
            self.assertEqual(stats["stop_reason"], "file_limit")
            with self.assertRaisesRegex(ValueError, "allow_incomplete"):
                build_index(output, root / "limited.sqlite3")
            build_index(output, root / "limited.sqlite3", allow_incomplete=True)

    def test_include_and_exclude_globs_select_primary_rfc_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "bcp").mkdir(parents=True)
            fixture = "Request for Comments: 9999\n\nA Test RFC\n\n1.  Introduction\n\nUseful text.\n"
            (source / "rfc9999.txt").write_text(fixture, encoding="utf-8")
            (source / "rfc-index.txt").write_text(fixture, encoding="utf-8")
            (source / "bcp" / "rfc9999.txt").write_text(fixture, encoding="utf-8")
            output = root / "processed"
            import_documentation(
                source,
                output,
                corpus="rfc-editor",
                source_version="snapshot-test",
                license_name="test",
                include_globs=("rfc*.txt",),
                exclude_globs=("rfc-index*.txt",),
            )
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            self.assertEqual([item["attributes"]["relative_path"] for item in documents], ["rfc9999.txt"])
            self.assertEqual(documents[0]["attributes"]["rfc_number"], 9999)
            manifest = json.loads((output / "corpus-manifest.json").read_text())
            self.assertEqual(manifest["configuration"]["include_globs"], ["rfc*.txt"])

    def test_docfx_includes_expand_into_canonical_pages_without_fragment_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "docs").mkdir(parents=True)
            (source / "includes").mkdir()
            (source / "docs" / "overview.md").write_text(
                "# Deployment\n\n[!INCLUDE [Shared guidance](~/includes/shared.md)]\n",
                encoding="utf-8",
            )
            (source / "includes" / "shared.md").write_text(
                "Use the framework-dependent deployment model.\n",
                encoding="utf-8",
            )
            output = root / "processed"
            import_documentation(
                source,
                output,
                corpus="dotnet-docs",
                source_version="test",
                license_name="test",
                include_globs=("docs/*.md", "docs/**/*.md"),
                resolve_docfx_includes=True,
            )
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            chunks = [json.loads(line) for line in (output / "chunks.jsonl").read_text().splitlines()]
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0]["attributes"]["relative_path"], "docs/overview.md")
            self.assertIn("framework-dependent deployment", chunks[0]["text"])
            manifest = json.loads((output / "corpus-manifest.json").read_text())
            self.assertTrue(manifest["configuration"]["resolve_docfx_includes"])

            (source / "docs" / "escape.md").write_text(
                "# Unsafe\n\n[!INCLUDE [Escape](../../outside.md)]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "escapes the source root"):
                import_documentation(
                    source,
                    root / "unsafe",
                    corpus="dotnet-docs",
                    source_version="test",
                    license_name="test",
                    include_globs=("docs/escape.md",),
                    resolve_docfx_includes=True,
                )

            (source / "docs" / "external.md").write_text(
                "# External include\n\nLocal context remains.\n\n[!INCLUDE [Cross repository](~/other-repo/shared.md)]\n",
                encoding="utf-8",
            )
            import_documentation(
                source,
                root / "external",
                corpus="dotnet-docs",
                source_version="test",
                license_name="test",
                include_globs=("docs/external.md",),
                resolve_docfx_includes=True,
                allow_missing_docfx_includes=True,
            )
            external_document = json.loads((root / "external/documents.jsonl").read_text().splitlines()[0])
            self.assertEqual(external_document["attributes"]["unresolved_docfx_includes"], ["other-repo/shared.md"])
            external_stats = json.loads((root / "external/extraction-stats.json").read_text())
            self.assertEqual(external_stats["unresolved_docfx_includes"], 1)

    def test_rfc_header_metadata_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "rfc9846.txt").write_text(
                """Internet Engineering Task Force (IETF)                 E. Example
Request for Comments: 9846                                 Independent
Obsoletes: 5077, 5246, 8446                                July 2026
Updates: 5705, 6066
Category: Standards Track
ISSN: 2070-1721

The Transport Layer Security Protocol Version 1.3

1.  Introduction

Protocol text.
""",
                encoding="utf-8",
            )
            output = root / "processed"
            import_documentation(
                source,
                output,
                corpus="rfc-editor-text",
                source_version="snapshot-test",
                license_name="test",
            )
            document = json.loads((output / "documents.jsonl").read_text().splitlines()[0])
            self.assertEqual(document["attributes"]["rfc_number"], 9846)
            self.assertEqual(document["attributes"]["obsoletes"], [5077, 5246, 8446])
            self.assertEqual(document["attributes"]["updates"], [5705, 6066])
            self.assertEqual(document["attributes"]["publication_status"], "Standards Track")
            self.assertEqual(document["attributes"]["publication_date"], "July 2026")
            self.assertEqual(document["attributes"]["issn"], "2070-1721")

    def test_single_archive_wrapper_does_not_change_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "release-1.0"
            wrapper.mkdir()
            source = self._source(wrapper)
            direct_output = root / "direct"
            wrapped_output = root / "wrapped"
            common = {
                "corpus": "test-docs",
                "source_version": "1",
                "license_name": "test",
                "base_url": "https://example.test/docs/",
            }
            import_documentation(source, direct_output, **common)
            import_documentation(wrapper, wrapped_output, **common)
            direct_documents = (direct_output / "documents.jsonl").read_text(encoding="utf-8")
            wrapped_documents = (wrapped_output / "documents.jsonl").read_text(encoding="utf-8")
            self.assertEqual(direct_documents, wrapped_documents)

    def test_version_pinned_source_url_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            output = root / "processed"
            import_documentation(
                source,
                output,
                corpus="test-docs",
                source_version="1.0",
                license_name="test",
                source_url_template="https://example.test/tree/{relative_path}?h=v1.0",
            )
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            self.assertEqual(documents[0]["source_url"], "https://example.test/tree/api.md?h=v1.0")
            with self.assertRaisesRegex(ValueError, "relative_path"):
                import_documentation(
                    source,
                    root / "invalid",
                    corpus="test-docs",
                    source_version="1.0",
                    license_name="test",
                    source_url_template="https://example.test/no-placeholder",
                )

    def test_explicit_content_subdirectory_scopes_identity_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".archive-name-encoding-v1.json").write_text(
                '{"schema_version":1,"encoded_members":1}\n', encoding="utf-8"
            )
            docs = root / "%50ackage" / "share" / "html"
            docs.mkdir(parents=True)
            (root / "README.md").write_text("# Package metadata\n\nDo not ingest this wrapper.", encoding="utf-8")
            (docs / "guide.html").write_text(
                "<title>Borrowing</title><h1>References</h1><p>A borrow has a lifetime.</p>", encoding="utf-8"
            )
            output = root / "processed"
            import_documentation(
                root,
                output,
                corpus="rust-docs",
                source_version="1",
                license_name="test",
                content_subdirectory="Package/share/html",
                source_url_template="https://example.test/{relative_path}",
            )
            document = json.loads((output / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(document["attributes"]["relative_path"], "guide.html")
            self.assertEqual(document["source_url"], "https://example.test/guide.html")
            manifest = json.loads((output / "corpus-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["configuration"]["content_subdirectory"], "Package/share/html")
            with self.assertRaisesRegex(ValueError, "inside source_root"):
                import_documentation(
                    root,
                    root / "invalid",
                    corpus="rust-docs",
                    source_version="1",
                    license_name="test",
                    content_subdirectory="../escape",
                )

    def test_portable_archive_names_decode_before_identity_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            (root / ".archive-name-encoding-v1.json").write_text(
                '{"schema_version":1,"encoded_members":1}\n', encoding="utf-8"
            )
            (release / "_%45xit.2").write_text('.TH _Exit 2\n.SH NAME\n_Exit \\- terminate process\n', encoding="utf-8")
            output = root / "processed"
            import_documentation(
                root,
                output,
                corpus="man-test",
                source_version="1",
                license_name="test",
                source_url_template="https://example.test/{relative_path}?h=v1",
                include_globs=("_Exit.2",),
            )
            document = json.loads((output / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(document["attributes"]["relative_path"], "_Exit.2")
            self.assertEqual(document["source_url"], "https://example.test/_Exit.2?h=v1")

    def test_case_distinct_upstream_paths_receive_unique_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".archive-name-encoding-v1.json").write_text(
                '{"schema_version":1,"encoded_members":2}\n', encoding="utf-8"
            )
            (root / "%49ndex.html").write_text(
                "<title>Capital Index</title><p>Capital-case index documentation.</p>", encoding="utf-8"
            )
            (root / "index.html").write_text(
                "<title>Lower Index</title><p>Lower-case index documentation.</p>", encoding="utf-8"
            )
            output = root / "processed"
            import_documentation(
                root,
                output,
                corpus="case-test",
                source_version="1",
                license_name="test",
                source_url_template="https://example.test/{relative_path}",
            )
            documents = [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]
            self.assertEqual(len({item["document_id"] for item in documents}), 2)
            self.assertEqual([item["attributes"]["relative_path"] for item in documents], ["Index.html", "index.html"])
            self.assertEqual(
                sum(bool(item["attributes"].get("case_distinct_path_collision")) for item in documents), 1
            )

    def test_existing_and_unrecognized_output_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            output = root / "processed"
            import_documentation(
                source,
                output,
                corpus="test-docs",
                source_version="1",
                license_name="test",
            )
            before = (output / "corpus-manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                import_documentation(
                    source,
                    output,
                    corpus="test-docs",
                    source_version="2",
                    license_name="test",
                )
            self.assertEqual((output / "corpus-manifest.json").read_bytes(), before)
            (output / "personal-notes.txt").write_text("preserve me")
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                import_documentation(
                    source,
                    output,
                    corpus="test-docs",
                    source_version="2",
                    license_name="test",
                    force=True,
                )
            self.assertEqual((output / "personal-notes.txt").read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()
