"""Compare final native slide content with the independently approved Page Spec."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def compact(value):
    # Whitespace may change when a paragraph is split into runs or lines.
    # Keep punctuation, case, decimal points, signs and units significant.
    return "".join(char for char in unicodedata.normalize("NFC", str(value)) if not char.isspace())


def text_present(value, segments):
    wanted = compact(value)
    if not wanted:
        return True
    prefix = r"(?<![0-9.,+\-−])" if wanted[0].isdigit() or wanted[0] in "+-−" else ""
    suffix = r"(?![0-9.,%‰])" if wanted[-1].isdigit() else ""
    pattern = prefix + re.escape(wanted) + suffix
    return any(re.search(pattern, compact(text)) is not None for text in segments)


def native_text_segments(root):
    # Join runs/paragraphs only inside the same logical text object or table
    # cell. Unrelated shapes containing "3" and "2%" must not satisfy "32%".
    text_bodies = root.findall(".//p:txBody", NS) + root.findall(".//a:txBody", NS)
    return ["\n".join("".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
                      for paragraph in body.findall("a:p", NS)) for body in text_bodies]


def cell_matches(expected, actual):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return Decimal(str(expected)) == Decimal(str(actual).strip())
        except InvalidOperation:
            return False
    return compact(expected) == compact(actual)


def table_rows(data):
    rows = data.get("rows") if isinstance(data, dict) else data
    if (not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]
            or any(not isinstance(row, list) or len(row) != len(rows[0])
                   or any(not isinstance(value, (str, int, float)) or isinstance(value, bool) for value in row)
                   for row in rows)):
        return None
    return rows


def rows_match(wanted, actual):
    return (len(wanted) == len(actual)
            and all(len(wrow) == len(arow) and all(cell_matches(w, a) for w, a in zip(wrow, arow))
                    for wrow, arow in zip(wanted, actual)))


def chart_data(root):
    def points(parent):
        if parent is None:
            raise ValueError("Native chart lacks a literal data cache")
        values = sorted((int(point.get("idx")), point.findtext("c:v", namespaces=NS))
                        for point in parent.findall("c:pt", NS))
        if [index for index, _ in values] != list(range(len(values))):
            raise ValueError("Native chart data cache has missing or duplicate indices")
        return [value for _, value in values]

    result = []
    for series in root.findall(".//c:ser", NS):
        name = series.findtext("c:tx/c:strRef/c:strCache/c:pt/c:v", namespaces=NS)
        if name is None:
            name = series.findtext("c:tx/c:v", default="", namespaces=NS)
        categories = series.find("c:cat/c:strRef/c:strCache", NS)
        if categories is None:
            categories = series.find("c:cat/c:strLit", NS)
        values = series.find("c:val/c:numRef/c:numCache", NS)
        if values is None:
            values = series.find("c:val/c:numLit", NS)
        result.append({"name": name, "categories": points(categories), "values": points(values)})
    return result


def chart_matches(data, actual):
    if (not isinstance(data, dict) or not isinstance(data.get("categories"), list)
            or not isinstance(data.get("series"), list) or len(data["series"]) != len(actual)):
        return False
    for wanted, delivered in zip(data["series"], actual):
        if (not isinstance(wanted, dict) or "values" not in wanted
                or not cell_matches(wanted.get("name", ""), delivered["name"])
                or not rows_match([data["categories"], wanted["values"]],
                                  [delivered["categories"], delivered["values"]])):
            return False
    return True


def check_approved_slide(slide, root, charts=()):
    """Native content is machine-checkable; raster meaning remains a visual task."""
    segments = native_text_segments(root)
    actual_tables = [[["".join(node.text or "" for node in cell.findall(".//a:t", NS))
                       for cell in row.findall("a:tc", NS)] for row in table.findall("a:tr", NS)]
                     for table in root.findall(".//a:tbl", NS)]
    actual_charts = [chart_data(chart) for chart in charts]
    errors, visual, required = [], [], []
    native_tables_checked = native_charts_checked = 0
    optional_text = {compact(element.get("text", "")) for element in slide.get("elements", [])
                     if element.get("kind") == "text" and element.get("native_intent") in {"raster", "either"}}
    if slide.get("title") and compact(slide["title"]) not in optional_text:
        required.append(("title", slide["title"]))
    for element in slide.get("elements", []):
        identifier, kind = element["id"], element.get("kind")
        intent = element.get("native_intent", "native")
        if element.get("confirmation_status") == "unresolved":
            visual.append({"element_id": identifier, "reason": "source content is unresolved"})
            continue
        if kind == "text":
            value = element.get("text", "")
            if intent == "raster" or (intent == "either" and not text_present(value, segments)):
                visual.append({"element_id": identifier, "reason": "approved non-native text requires visual comparison"})
            else:
                required.append((identifier, value))
        elif kind == "table" and intent != "raster" and "preserve_asset" not in element:
            rows = table_rows(element.get("data"))
            match = next((index for index, actual in enumerate(actual_tables)
                          if rows is not None and rows_match(rows, actual)), None)
            if match is not None:
                actual_tables.pop(match)
                native_tables_checked += 1
            elif intent == "native":
                errors.append({"element_id": identifier, "reason": "approved native table is missing or its rows/cells differ"})
            else:
                visual.append({"element_id": identifier, "reason": "table data requires visual comparison"})
        elif kind == "chart" and intent != "raster" and "preserve_asset" not in element:
            match = next((index for index, actual in enumerate(actual_charts)
                          if chart_matches(element.get("data"), actual)), None)
            if match is not None:
                actual_charts.pop(match)
                native_charts_checked += 1
            elif intent == "native":
                errors.append({"element_id": identifier, "reason": "approved native chart is missing or its categories/series differ; use the Scene chart route"})
            else:
                visual.append({"element_id": identifier, "reason": "chart data requires visual comparison"})
        elif kind in {"image", "table", "chart"}:
            visual.append({"element_id": identifier, "reason": "raster/source-preserved content requires visual comparison"})
    seen = set()
    for identifier, text in required:
        if compact(text) in seen:
            continue
        seen.add(compact(text))
        if not text_present(text, segments):
            errors.append({"element_id": identifier, "reason": "approved native text is missing or changed", "expected": text})
    # Mandatory visible strings may belong to a raster chart or protected image.
    # Do not pretend that absence from XML is OCR evidence about those pixels.
    for text in slide.get("required_visible_values", []):
        if compact(text) not in seen and not text_present(text, segments):
            visual.append({"element_id": "required_visible_values", "expected": text,
                           "reason": "visible value is not available as native text; compare the rendered page"})
    return {"errors": errors, "native_text_checked": len(seen),
            "native_tables_checked": native_tables_checked, "native_charts_checked": native_charts_checked,
            "visual_review_required": visual}
