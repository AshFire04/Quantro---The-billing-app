import os

from tests.test_auth import create

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_template_or_code_file_starts_with_a_byte_order_mark():
    # A BOM at the start of a template is printed into the page and pushes the top bar down.
    for folder in ("templates", "app", "static"):
        for base, _, names in os.walk(os.path.join(ROOT, folder)):
            for name in names:
                if name.endswith((".html", ".py", ".css", ".js")):
                    with open(os.path.join(base, name), "rb") as f:
                        assert f.read(3) != b"\xef\xbb\xbf", f"{name} starts with a BOM"


def test_pages_start_with_the_doctype(client):
    assert client.get("/login").data.lstrip(b" \r\n").startswith(b"<!doctype html>")
    assert client.get("/login").data.startswith(b"<!doctype html>")
    create(client)
    for url in ("/billing", "/bills", "/settings", "/inventory/"):
        body = client.get(url).data
        assert body.startswith(b"<!doctype html>"), url
        assert "﻿" not in body.decode(), url