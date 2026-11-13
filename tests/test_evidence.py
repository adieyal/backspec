from reqx.modules.evidence.domain import (Chunk, Observation, RawObservation, Rejected, pack, render,
                                          split_file, verify)

LINES = ["def pay(order):", "    if order.total > LIMIT:", "        raise OverLimit()", "    charge(order)", ""]
FILES = {"pay.py": LINES}
HASHES = {"pay.py": "sha256:abc"}


def raw(**changes):
    base = dict(path="pay.py", lines=[2, 3], quote="if order.total > LIMIT:", kind="validation",
                statement="An order over the limit is refused.")
    return RawObservation(**{**base, **changes})


def test_a_quote_inside_its_lines_is_exact():
    checked = verify(raw(), {"pay.py"}, FILES, HASHES)
    assert isinstance(checked, Observation) and checked.verified == "exact" and checked.lines == (2, 3)


def test_a_quote_found_once_elsewhere_moves_the_range():
    checked = verify(raw(lines=[4, 5]), {"pay.py"}, FILES, HASHES)
    assert checked.verified == "repaired" and checked.lines[0] <= 2 <= checked.lines[1]


def test_a_copied_line_number_prefix_is_ignored():
    assert verify(raw(quote="    2|     if order.total > LIMIT:"), {"pay.py"}, FILES, HASHES).verified == "exact"


def test_what_cannot_be_found_is_rejected_with_the_reason():
    for changes, reason in ((dict(quote="if order.total > 9000:"), "quote not found"),
                            (dict(path="other.py"), "path was not shown to the model"),
                            (dict(quote="x"), "no usable quote"),
                            (dict(statement=" "), "no statement")):
        checked = verify(raw(**changes), {"pay.py"}, FILES, HASHES)
        assert isinstance(checked, Rejected) and checked.reason == reason


def test_a_quote_that_appears_twice_outside_its_range_is_rejected():
    files = {"pay.py": ["return None", "x = 1", "return None"]}
    checked = verify(raw(lines=[2, 2], quote="return None"), {"pay.py"}, files, HASHES)
    assert isinstance(checked, Rejected) and checked.reason == "quote found more than once"


def test_the_same_observation_gets_the_same_id():
    assert verify(raw(), {"pay.py"}, FILES, HASHES).id == verify(raw(), {"pay.py"}, FILES, HASHES).id


def test_every_line_keeps_its_real_number_when_a_file_is_split():
    lines = [f"line {n}" for n in range(1, 251)]
    chunks = split_file("big.py", lines, 100)
    assert [c.first for c in chunks] == [1, 101, 201] and chunks[-1].last == 250
    text = render(chunks[1:2])
    assert "=== FILE: big.py (lines 101-200) ===" in text and "  101| line 101" in text


def test_batches_never_exceed_the_limit_unless_one_chunk_does():
    chunks = [Chunk("a", 1, ("x",) * 60), Chunk("b", 1, ("x",) * 60), Chunk("c", 1, ("x",) * 30)]
    assert [[c.path for c in batch] for batch in pack(chunks, 100)] == [["a"], ["b", "c"]]


def test_a_change_is_found_line_by_line():
    from reqx.modules.evidence.domain import compare, line_digest, windows
    old = ["a = 1", "b = 2", "c = 3", "d = 4", "e = 5"]
    new = ["# header", "a = 1", "b = 2", "c = 30", "d = 4", "e = 5", "f = 6"]
    change = compare(line_digest(old), new)
    assert change.changed == ((1, 1), (4, 4), (7, 7))
    assert change.moved(1, 2) == (2, 3) and change.moved(4, 5) == (5, 6)
    assert change.moved(2, 3) is None and change.moved(3, 3) is None   # a range that includes a changed line
    assert change.touches(3, 4) and not change.touches(2, 3)
    assert windows(change.changed, 7, context=1) == [(1, 7)]   # touching windows are merged
    assert windows(((2, 2), (40, 41)), 100, context=3) == [(1, 5), (37, 44)]
    assert compare(line_digest(old), old).changed == ()


def test_an_observation_id_follows_the_cited_text_not_its_position():
    from reqx.modules.evidence.domain import observation_id
    assert observation_id("a.py", ["  x = 1", "y = 2"], "S.") == observation_id("a.py", ["x = 1", "  y = 2"], " S. ")
    assert observation_id("a.py", ["x = 1"], "S.") != observation_id("a.py", ["x = 2"], "S.")
    assert observation_id("a.py", ["x = 1"], "S.") != observation_id("b.py", ["x = 1"], "S.")
