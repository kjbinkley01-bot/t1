"""For Each Row: loop over CSV and Excel rows with one variable per column."""

import zipfile

from clicker import datafile, flow, model
from helpers import S, run, script


def write_xlsx(path, rows, sheet="People"):
    """A minimal real .xlsx: shared strings for text, numbers as numbers, one date cell style."""
    strings = []

    def cell(ref, v, date=False):
        if isinstance(v, (int, float)):
            style = ' s="1"' if date else ""
            return f'<c r="{ref}"{style}><v>{v}</v></c>'
        strings.append(v)
        return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
    body = []
    for r, row in enumerate(rows, 1):
        cells = "".join(cell(f"{'ABCDEFG'[c]}{r}", v, date=(c == 2 and r > 1)) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    m = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {m} {rel}><sheets><sheet name="{sheet}" sheetId="1" '
                                      f'r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {m}><sheetData>{"".join(body)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst {m}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/styles.xml", f'<styleSheet {m}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/>'
                                    f'</cellXfs></styleSheet>')


def test_csv_rows_become_variables(fake_inputs, screen, tmp_path):
    p = tmp_path / "people.csv"
    p.write_text("Name,Email Address\nAda,ada@x.io\nLin,lin@x.io\n,\nBo,bo@x.io\n", encoding="utf-8")
    sc = script(S("For Each Row", file=str(p)), S("Type Text", text="{row}/{row_count} {name} <{email_address}>"),
                S("Next Row"), S("Type Text", text="done"))
    r, _ = run(sc)
    assert r.result[0], r.result
    typed = [c[1] for c in fake_inputs.calls if c[0] == "type"]
    assert typed == ["1/3 Ada <ada@x.io>", "2/3 Lin <lin@x.io>", "3/3 Bo <bo@x.io>", "done"]


def test_start_row_and_max_rows(fake_inputs, screen, tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("n\n1\n2\n3\n4\n5\n", encoding="utf-8")
    run(script(S("For Each Row", file=str(p), start_row=2, max_rows=2), S("Type Text", text="{n}@{row}"),
               S("Next Row")))
    assert [c[1] for c in fake_inputs.calls if c[0] == "type"] == ["2@2", "3@3"]


def test_xlsx_with_semicolons_dates_and_sheet_names(fake_inputs, screen, tmp_path):
    p = tmp_path / "book.xlsx"
    write_xlsx(p, [["Name", "Qty", "Due"], ["Ada", 3, 46053], ["Lin", 12.0, 46054]])
    names, rows = datafile.read_table(str(p), "people")
    assert names == ["name", "qty", "due"]
    assert rows == [["Ada", "3", "2026-01-31"], ["Lin", "12", "2026-02-01"]]
    run(script(S("For Each Row", file=str(p), sheet="People"), S("Type Text", text="{name} x{qty}"), S("Next Row")))
    assert [c[1] for c in fake_inputs.calls if c[0] == "type"] == ["Ada x3", "Lin x12"]
    s = tmp_path / "semi.csv"
    s.write_text("a;b\n1;2\n", encoding="utf-8")
    assert datafile.read_table(str(s)) == (["a", "b"], [["1", "2"]])


def test_missing_file_fails_clearly(fake_inputs, screen):
    r, _ = run(script(S("For Each Row", file="C:/nope.csv"), S("Next Row")))
    assert not r.result[0] and "not found" in r.result[1]


def test_blocks_must_close_with_the_right_end():
    steps = script(S("For Each Row", file="a.csv"), S("Beep"), S("End While"))["steps"]
    _p, err = model.match_blocks(steps)
    assert "needs Next Row" in err
    steps = script(S("For Each Row", file="a.csv"), S("While Variable", var="x", op="=", value="1"),
                   S("End While"), S("Next Row"))["steps"]
    pairs, err = model.match_blocks(steps)
    assert err is None and pairs[0] == 3 and pairs[1] == 2
    assert {(e["kind"], e["src"], e["dst"]) for e in flow.edges(steps)} == {("while", 0, 3), ("while", 1, 2)}
    assert flow.unreachable({"steps": steps}) == []
