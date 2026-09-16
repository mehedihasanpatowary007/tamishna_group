import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET


XLSX_MIMETYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
}
CSV_MIMETYPES = {
    "text/csv",
    "application/csv",
    "text/plain",
}

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def is_xlsx_file(filename="", mimetype=""):
    name = (filename or "").lower()
    mime = (mimetype or "").lower()
    return name.endswith((".xlsx", ".xlsm")) or mime in XLSX_MIMETYPES


def is_csv_file(filename="", mimetype=""):
    name = (filename or "").lower()
    mime = (mimetype or "").lower()
    return name.endswith(".csv") or mime in CSV_MIMETYPES and name.endswith((".csv", ".txt"))


def _column_index(cell_ref):
    match = re.match(r"([A-Za-z]+)", cell_ref or "")
    if not match:
        return 0
    result = 0
    for ch in match.group(1).upper():
        result = result * 26 + (ord(ch) - 64)
    return max(result - 1, 0)


def _node_text(node):
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _read_shared_strings(zf):
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    values = []
    for si in root.findall(f"{{{_MAIN_NS}}}si"):
        texts = []
        direct = si.find(f"{{{_MAIN_NS}}}t")
        if direct is not None:
            texts.append(direct.text or "")
        for run in si.findall(f"{{{_MAIN_NS}}}r"):
            t = run.find(f"{{{_MAIN_NS}}}t")
            if t is not None:
                texts.append(t.text or "")
        values.append("".join(texts))
    return values


def _sheet_targets(zf):
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {}
    for rel in rels.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        rel_map[rel.attrib.get("Id")] = rel.attrib.get("Target", "")

    sheets = []
    sheets_node = workbook.find(f"{{{_MAIN_NS}}}sheets")
    if sheets_node is None:
        return sheets
    for sheet in sheets_node.findall(f"{{{_MAIN_NS}}}sheet"):
        name = sheet.attrib.get("name", "Sheet")
        rid = sheet.attrib.get(f"{{{_REL_NS}}}id")
        target = rel_map.get(rid, "")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        sheets.append((name, path))
    return sheets


def _cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_MAIN_NS}}}is")
        return _node_text(inline)
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    raw = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if cell_type in {"str", "e"}:
        return raw
    return raw


def extract_xlsx_text(raw_bytes, filename="workbook.xlsx", max_sheets=8, max_rows_per_sheet=1200, max_cols=80, max_chars=160000):
    """Extract a compact row-oriented text representation from an XLSX/XLSM file.

    Uses only Python's standard library so it is deployable on Odoo.sh without
    adding a Python package dependency. It intentionally reads values only;
    formulas use their cached values when present.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
            if not required.issubset(set(zf.namelist())):
                raise ValueError("Workbook structure is incomplete")
            shared_strings = _read_shared_strings(zf)
            sheets = _sheet_targets(zf)[:max_sheets]
            output = [f"Workbook: {filename}"]
            char_count = len(output[0])

            for sheet_name, sheet_path in sheets:
                if sheet_path not in zf.namelist():
                    continue
                root = ET.fromstring(zf.read(sheet_path))
                sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
                if sheet_data is None:
                    continue
                output.append(f"\nSheet: {sheet_name}")
                char_count += len(sheet_name) + 10
                rows_seen = 0
                for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
                    if rows_seen >= max_rows_per_sheet or char_count >= max_chars:
                        break
                    cells = {}
                    max_col = -1
                    for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                        col = _column_index(cell.attrib.get("r", ""))
                        if col >= max_cols:
                            continue
                        value = _cell_value(cell, shared_strings)
                        if value not in (None, ""):
                            cells[col] = str(value).strip()
                            max_col = max(max_col, col)
                    if max_col < 0:
                        continue
                    values = [cells.get(idx, "") for idx in range(max_col + 1)]
                    # Keep internal blanks to preserve column alignment but trim trailing blanks.
                    while values and values[-1] == "":
                        values.pop()
                    row_no = row.attrib.get("r", str(rows_seen + 1))
                    line = f"Row {row_no}: " + " | ".join(values)
                    output.append(line)
                    char_count += len(line) + 1
                    rows_seen += 1

                if rows_seen >= max_rows_per_sheet:
                    output.append(f"[Sheet truncated after {max_rows_per_sheet} non-empty rows]")
                if char_count >= max_chars:
                    output.append("[Workbook text truncated for processing safety]")
                    break

            return "\n".join(output).strip()
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as exc:
        raise ValueError(f"Could not read Excel workbook: {exc}") from exc


def extract_csv_text(raw_bytes, filename="document.csv", max_rows=3000, max_chars=160000):
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Could not decode CSV file")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    output = [f"CSV file: {filename}"]
    char_count = len(output[0])
    reader = csv.reader(io.StringIO(text), dialect)
    for idx, row in enumerate(reader, start=1):
        if idx > max_rows or char_count >= max_chars:
            output.append("[CSV text truncated for processing safety]")
            break
        values = [str(value).strip() for value in row]
        while values and values[-1] == "":
            values.pop()
        if not any(values):
            continue
        line = f"Row {idx}: " + " | ".join(values)
        output.append(line)
        char_count += len(line) + 1
    return "\n".join(output).strip()
