"""The HTML report: one self-contained page drawn from the result."""
import json
import re

from typer.testing import CliRunner

from reqx.host.cli import app
from reqx.host.composition import Config, extract
from reqx.modules.report.facade import formats, render
from tests.test_pipeline import fake, repo


def result_of(tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()
    return extract(repo(folder), Config(provider=fake(), use_cache=False))


def embedded(page: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="reqx-data">(.*?)</script>', page, re.S).group(1))


def test_html_is_a_known_format():
    assert "html" in formats()


def test_the_page_carries_every_requirement_with_its_evidence(tmp_path):
    result = result_of(tmp_path)
    data = embedded(render(result, "html").text)
    assert [r["id"] for r in data["requirements"]] == [r.id for r in result.requirements]
    assert all(r["evidence"] and r["evidence"][0]["quote"] for r in data["requirements"])
    assert {f["path"] for f in data["coverage"]["files"]} == {f.path for f in result.coverage.files}


def test_the_page_is_one_document_that_loads_nothing_from_outside(tmp_path):
    page = render(result_of(tmp_path), "html").text
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert not re.search(r'<(script|link|img)[^>]*\s(src|href)=', page)
    assert "http://" not in page and "https://" not in page


def test_text_from_the_codebase_cannot_close_the_data_block(tmp_path):
    result = result_of(tmp_path)
    hostile = "</script><script>alert(1)</script>"
    result.requirements[0].statement = hostile
    page = render(result, "html").text
    assert hostile not in page
    assert embedded(page)["requirements"][0]["statement"] == hostile


def test_the_title_is_the_folder_name_unless_one_is_given(tmp_path):
    result = result_of(tmp_path)
    assert "<title>repo requirements</title>" in render(result, "html").text
    assert "<title>Shop &amp; stock requirements</title>" in render(result, "html", title="Shop & stock").text


def test_what_only_a_later_run_needs_is_left_out_of_the_page(tmp_path):
    data = embedded(render(result_of(tmp_path), "html").text)
    assert "assignments" not in data
    assert all("line_digest" not in f and "source_hash" not in f for f in data["coverage"]["files"])


def test_a_fragment_has_no_document_wrapper(tmp_path):
    page = render(result_of(tmp_path), "html", fragment=True).text
    assert page.startswith("<title>") and "<html" not in page and "<body" not in page


def test_render_writes_the_page_from_a_saved_result(tmp_path):
    saved = tmp_path / "result.json"
    saved.write_text(result_of(tmp_path).to_json(), encoding="utf-8")
    out = tmp_path / "report.html"
    done = CliRunner().invoke(app, ["render", str(saved), "--format", "html", "-o", str(out), "--title", "Shop"])
    assert done.exit_code == 0, done.output
    assert "<title>Shop requirements</title>" in out.read_text(encoding="utf-8")
