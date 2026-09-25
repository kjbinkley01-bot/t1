"""Reading rows from CSV and Excel (.xlsx) files for the For Each Row loop, without extra libraries."""

import csv
import datetime
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def var_name(header, n):
    """'Email Address' -> 'email_address'; blank or odd headers become col1, col2 ..."""
    v = re.sub(r"[^A-Za-z0-9_]+", "_", str(header or "").strip()).strip("_").lower()
    if not v or v[0].isdigit():
        v = f"col{n}" if not v else f"c_{v}"
    return v


def read_table(path, sheet=""):
    """(headers, rows) where rows are lists of strings. The first row holds the column names."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"spreadsheet not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        table = _read_xlsx(path, sheet)
    elif ext == ".xls":
        raise ValueError("Old .xls files aren't supported; save it as .xlsx or .csv")
    else:
        table = _read_csv(path)
    table = [r for r in table if any(str(c).strip() for c in r)]
    if not table:
        return [], []
    width = max(len(r) for r in table)
    table = [list(r) + [""] * (width - len(r)) for r in table]
    names, seen = [], set()
    for n, h in enumerate(table[0], 1):
        v = var_name(h, n)
        base, k = v, 2
        while v in seen:
            v = f"{base}_{k}"
            k += 1
        seen.add(v)
        names.append(v)
    return names, table[1:]


def rows_as_dicts(path, sheet=""):
    names, rows = read_table(path, sheet)
    return [dict(zip(names, r)) for r in rows]


def _read_csv(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _excel_date(serial):
    try:
        d = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(serial))
    except (ValueError, OverflowError):
        return str(serial)
    return d.strftime("%Y-%m-%d") if d.time() == datetime.time(0) else d.strftime("%Y-%m-%d %H:%M")


def _date_styles(z):
    """Indexes of cell styles that show dates, so date cells read as 2026-01-31 instead of 46053."""
    try:
        root = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return set()
    custom = {}
    for nf in root.findall("m:numFmts/m:numFmt", NS):
        custom[int(nf.get("numFmtId"))] = nf.get("formatCode", "")
    out = set()
    xfs = root.find("m:cellXfs", NS)
    for k, xf in enumerate(xfs.findall("m:xf", NS) if xfs is not None else []):
        fid = int(xf.get("numFmtId", "0"))
        code = custom.get(fid, "")
        if 14 <= fid <= 22 or 45 <= fid <= 47 or (code and re.search(r"[dy]", code.split(";")[0].lower())
                                                    and "[" not in code):
            out.add(k)
    return out


def _read_xlsx(path, sheet=""):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = wb.findall("m:sheets/m:sheet", NS)
        if not sheets:
            return []
        chosen = sheets[0]
        if sheet:
            for sh in sheets:
                if sh.get("name", "").lower() == sheet.lower():
                    chosen = sh
                    break
            else:
                raise ValueError(f"no sheet named '{sheet}' (sheets: {', '.join(s.get('name') for s in sheets)})")
        rid = chosen.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels.findall("pr:Relationship", NS) if r.get("Id") == rid)
        target = target.lstrip("/")
        part = target if target.startswith("xl/") else "xl/" + target
        dates = _date_styles(z)
        root = ET.fromstring(z.read(part))
        rows = []
        for row in root.iter(f"{{{NS['m']}}}row"):
            cells = {}
            for c in row.findall("m:c", NS):
                ref, t = c.get("r", ""), c.get("t")
                v = c.find("m:v", NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                elif t == "b" and v is not None:
                    val = "TRUE" if v.text == "1" else "FALSE"
                elif v is not None and v.text is not None:
                    val = v.text
                    if c.get("s") and int(c.get("s")) in dates:
                        val = _excel_date(val)
                    elif re.fullmatch(r"-?\d+\.0+", val):
                        val = val.split(".")[0]
                else:
                    val = ""
                if ref:
                    cells[_col_index(ref)] = val
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(k, "") for k in range(width)])
        return rows
