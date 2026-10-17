"""Scene-native rectangular table spans and deterministic grid geometry.

Design informed by ningzimu/image-to-editable-ppt-skill; see
references/upstream-editable.md for provenance and license.
"""

from __future__ import annotations


def merge_owners(element):
    """Validate spans without mutating the Scene; map covered slots to origins."""
    rows = element["rows"]
    owners = {}
    occupied = set()
    for span in element.get("merges", []):
        r, c = span["row"], span["col"]
        rs, cs = span["row_span"], span["col_span"]
        if rs == cs == 1:
            raise ValueError("Table merge must cover at least two cells")
        if r + rs > len(rows) or c + cs > len(rows[0]):
            raise ValueError("Table merge exceeds grid bounds")
        cells = {(rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs)}
        if occupied & cells:
            raise ValueError("Table merges overlap")
        occupied.update(cells)
        for slot in cells - {(r, c)}:
            if rows[slot[0]][slot[1]] != "":
                raise ValueError("Covered table cells must be empty; put text in the merge origin")
            owners[slot] = (r, c)
    return owners


def scaled_lengths(weights, extent):
    """Positive EMU lengths with exact total, including the rounding remainder."""
    # Normalize by the maximum first so finite large weights cannot overflow sum.
    maximum = max(weights)
    normalized = [weight / maximum for weight in weights]
    total = sum(normalized)
    lengths = [round(extent * value / total) for value in normalized]
    lengths[-1] += extent - sum(lengths)
    if any(value <= 0 for value in lengths):
        raise ValueError("Table row/column weights produce a zero-sized grid cell")
    return lengths


def grid_lengths(element, width, height):
    return (
        scaled_lengths(element.get("column_widths", [1] * len(element["rows"][0])), width),
        scaled_lengths(element.get("row_heights", [1] * len(element["rows"])), height),
    )


def table_errors(table, element, width, height):
    """Inspect the saved grid and merges as well as displayed cell text."""
    rows = element["rows"]
    if len(table.rows) != len(rows) or len(table.columns) != len(rows[0]):
        return ["table grid dimensions differ"]
    errors = []
    if [[cell.text for cell in row.cells] for row in table.rows] != rows:
        errors.append("table content differs")
    widths, heights = grid_lengths(element, width, height)
    if any(abs(col.width - wanted) > 4 for col, wanted in zip(table.columns, widths)):
        errors.append("table column widths differ")
    if any(abs(row.height - wanted) > 4 for row, wanted in zip(table.rows, heights)):
        errors.append("table row heights differ")
    owners = merge_owners(element)
    origins = {(span["row"], span["col"]): (span["row_span"], span["col_span"])
               for span in element.get("merges", [])}
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            span = origins.get((r, c))
            if (cell.is_spanned != ((r, c) in owners)
                    or cell.is_merge_origin != (span is not None)
                    or (span and (cell.span_height, cell.span_width) != span)):
                errors.append(f"table merge differs at cell {r},{c}")
    return errors
