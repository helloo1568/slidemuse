import hashlib
import io
import json
import math
import posixpath
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps


IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
PPT_EXTS = {".ppt", ".pptx"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": REL_NS,
}


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def collect_paragraph_text(root):
    paragraphs = []
    for paragraph in root.findall(".//a:p", NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def notes_body_text(root):
    """Read the speaker-note body without dropping blank lines or placeholders."""
    for shape in root.findall(".//p:sp", NS):
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if placeholder is None or placeholder.get("type") != "body":
            continue
        paragraphs = []
        for paragraph in shape.findall("p:txBody/a:p", NS):
            paragraphs.append("".join(
                "\v" if child.tag == f"{{{NS['a']}}}br" else
                "".join(node.text or "" for node in child.iter(f"{{{NS['a']}}}t"))
                for child in paragraph))
        return "\n".join(paragraphs)
    return ""


def approved_notes_contract(deck, root):
    """Load the independent, hash-bound SlideMuse Page Spec note contract."""
    name = deck.get("slidemuse_content", "slidemuse-page-content.json")
    snapshot = (root / name).resolve()
    if not snapshot.is_relative_to(root.resolve()):
        raise ValueError("Approved content snapshot must stay inside the run directory")
    if "slidemuse_content" not in deck and not snapshot.exists():
        return None
    data = snapshot.read_bytes()
    if ("slidemuse_content" in deck
            and hashlib.sha256(data).hexdigest() != deck.get("slidemuse_content_sha256")):
        raise ValueError("Approved content snapshot changed or lacks its recorded hash")
    slides = json.loads(data)["slides"]
    if len(slides) != int(deck.get("page_count", len(deck.get("pages", [])))):
        raise ValueError("Approved content slide count differs from the rebuild run")
    return {index: slide.get("speaker_notes", "").replace("\r\n", "\n").replace("\r", "\n")
            for index, slide in enumerate(slides, 1)}


def copy_input(src, input_dir):
    src = Path(src).resolve()
    dest = input_dir / src.name
    counter = 2
    while dest.exists() and dest.resolve() != src:
        dest = input_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    if src != dest:
        shutil.copy2(src, dest)
    return dest


def save_image_page(src, page_dir):
    page_dir.mkdir(parents=True, exist_ok=True)
    out = page_dir / "source.png"
    with Image.open(src) as image:
        ImageOps.exif_transpose(image).convert("RGB").save(out)
    return out


def render_pdf_pages(pdf_path, pages_dir, dpi):
    import pymupdf as fitz

    doc = fitz.open(pdf_path)
    outputs = []
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    for index, page in enumerate(doc, start=1):
        page_dir = pages_dir / f"page_{index:03d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out = page_dir / "source.png"
        pix.save(out)
        outputs.append(out)
    return outputs


def rel_source_part(rels_name):
    directory = posixpath.dirname(rels_name)
    if directory.endswith("/_rels"):
        directory = posixpath.dirname(directory)
    source = posixpath.basename(rels_name)[:-5]
    return posixpath.normpath(posixpath.join(directory, source))


def resolve_target(rels_name, target):
    source = rel_source_part(rels_name)
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), target))


def collect_notes_from_pptx(pptx_path, notes_dir=None):
    notes = []
    if notes_dir:
        notes_dir = Path(notes_dir)
    with zipfile.ZipFile(pptx_path) as z:
        names = set(z.namelist())
        if "ppt/presentation.xml" not in names or "ppt/_rels/presentation.xml.rels" not in names:
            return notes
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        pres_rels = ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
        rels_by_id = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in pres_rels.findall("rel:Relationship", NS)}
        slide_parts = []
        for sld_id in pres.findall(".//p:sldId", NS):
            rel_id = sld_id.attrib.get(f"{{{NS['r']}}}id")
            target = rels_by_id.get(rel_id)
            if target:
                slide_parts.append(posixpath.normpath(posixpath.join("ppt", target)))
        for page_index, slide_part in enumerate(slide_parts, start=1):
            rels_name = f"{posixpath.dirname(slide_part)}/_rels/{posixpath.basename(slide_part)}.rels"
            note = {"page_index": page_index, "text": "", "text_sha256": sha256_text(""), "source_slide": slide_part}
            if rels_name in names:
                root = ET.fromstring(z.read(rels_name))
                for rel in root.findall("rel:Relationship", NS):
                    if rel.attrib.get("Type", "").endswith("/notesSlide"):
                        notes_part = resolve_target(rels_name, rel.attrib.get("Target", ""))
                        if notes_part in names:
                            notes_bytes = z.read(notes_part)
                            notes_root = ET.fromstring(notes_bytes)
                            text = notes_body_text(notes_root)
                            update = {
                                "text": text,
                                "text_sha256": sha256_text(text),
                                "source_notes_part": notes_part,
                            }
                            if notes_dir:
                                out_dir = notes_dir / f"page_{page_index:03d}"
                                out_dir.mkdir(parents=True, exist_ok=True)
                                notes_xml = out_dir / "notesSlide.xml"
                                notes_xml.write_bytes(notes_bytes)
                                update["notes_xml"] = str(notes_xml)
                            note.update(update)
            if note["text"]:
                notes.append(note)
    return notes


def slide_parts_from_pptx(zip_file):
    names = set(zip_file.namelist())
    if "ppt/presentation.xml" not in names or "ppt/_rels/presentation.xml.rels" not in names:
        raise ValueError("PPTX is missing presentation relationships.")
    pres = ET.fromstring(zip_file.read("ppt/presentation.xml"))
    pres_rels = ET.fromstring(zip_file.read("ppt/_rels/presentation.xml.rels"))
    rels_by_id = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in pres_rels.findall("rel:Relationship", NS)}
    slide_parts = []
    for sld_id in pres.findall(".//p:sldId", NS):
        rel_id = sld_id.attrib.get(f"{{{NS['r']}}}id")
        target = rels_by_id.get(rel_id)
        if target:
            slide_parts.append(posixpath.normpath(posixpath.join("ppt", target)))
    if not slide_parts:
        raise ValueError("PPTX has no slides.")
    return slide_parts


def slide_size_from_pptx(zip_file):
    pres = ET.fromstring(zip_file.read("ppt/presentation.xml"))
    size = pres.find(".//p:sldSz", NS)
    if size is None:
        raise ValueError("PPTX is missing slide size.")
    return int(size.attrib["cx"]), int(size.attrib["cy"])


def slide_relationships(zip_file, slide_part):
    rels_name = f"{posixpath.dirname(slide_part)}/_rels/{posixpath.basename(slide_part)}.rels"
    if rels_name not in zip_file.namelist():
        return {}
    root = ET.fromstring(zip_file.read(rels_name))
    return {rel.attrib.get("Id"): rel for rel in root.findall("rel:Relationship", NS)}


def full_slide_picture_target(zip_file, slide_part, slide_cx, slide_cy):
    slide_root = ET.fromstring(zip_file.read(slide_part))
    if collect_paragraph_text(slide_root):
        raise ValueError(f"{slide_part} contains native text and is not an image-based slide.")
    pictures = slide_root.findall(".//p:pic", NS)
    if len(pictures) != 1:
        raise ValueError(f"{slide_part} must contain exactly one full-slide picture; found {len(pictures)}.")
    picture = pictures[0]
    properties = picture.find("p:nvPicPr/p:cNvPr", NS)
    if properties is not None and properties.get("hidden", "0").lower() in {"1", "true"}:
        raise ValueError(f"{slide_part} has a hidden picture; render the slide before rebuilding.")
    tree = slide_root.find("p:cSld/p:spTree", NS)
    if tree is None or picture not in list(tree) or any(
        child.tag.rsplit("}", 1)[-1] not in {"nvGrpSpPr", "grpSpPr", "pic", "extLst"}
        for child in tree
    ):
        raise ValueError(f"{slide_part} contains overlaid or grouped objects; render the slide before rebuilding.")
    blip = picture.find(".//a:blip", NS)
    if blip is None:
        raise ValueError(f"{slide_part} picture has no embedded image.")
    rel_id = blip.attrib.get(f"{{{NS['r']}}}embed")
    relationships = slide_relationships(zip_file, slide_part)
    rel = relationships.get(rel_id)
    if rel is None or not rel.attrib.get("Type", "").endswith("/image"):
        raise ValueError(f"{slide_part} picture relationship is not an embedded image.")

    transform = picture.find("p:spPr/a:xfrm", NS)
    if transform is None or (int(transform.get("rot", "0")) % 21600000
            or any(transform.get(key, "0").lower() in {"1", "true"} for key in ("flipH", "flipV"))):
        raise ValueError(f"{slide_part} has a rotated/flipped picture; render the slide before rebuilding.")
    off = transform.find("a:off", NS)
    ext = transform.find("a:ext", NS)
    if off is None or ext is None:
        raise ValueError(f"{slide_part} picture has no placement transform.")
    x, y = int(off.attrib.get("x", 0)), int(off.attrib.get("y", 0))
    cx, cy = int(ext.attrib.get("cx", 0)), int(ext.attrib.get("cy", 0))
    tolerance = 2
    if abs(x) > tolerance or abs(y) > tolerance or abs(cx - slide_cx) > tolerance or abs(cy - slide_cy) > tolerance:
        raise ValueError(f"{slide_part} picture is not full-slide.")
    geometry = picture.find("p:spPr/a:prstGeom", NS)
    effects = picture.find("p:spPr/a:effectLst", NS)
    fill = picture.find("p:blipFill", NS)
    fill_rect = picture.find("p:blipFill/a:stretch/a:fillRect", NS)
    line = picture.find("p:spPr/a:ln", NS)
    if (geometry is not None and geometry.get("prst") != "rect"
            or picture.find("p:spPr/a:custGeom", NS) is not None
            or effects is not None and len(effects)
            or line is not None and line.find("a:noFill", NS) is None
            or any(child.tag != f"{{{NS['a']}}}extLst" for child in blip)
            or fill is None or fill.find("a:tile", NS) is not None
            or fill_rect is None or any(float(value) for value in fill_rect.attrib.values())):
        raise ValueError(f"{slide_part} has unsupported picture styling; render the slide before rebuilding.")
    source_rect = picture.find("p:blipFill/a:srcRect", NS)
    crop = [float(source_rect.get(key, "0")) / 100000 if source_rect is not None else 0.0
            for key in ("l", "t", "r", "b")]
    if (not all(math.isfinite(value) and 0 <= value < 1 for value in crop)
            or crop[0] + crop[2] >= 1 or crop[1] + crop[3] >= 1):
        raise ValueError(f"{slide_part} has unsupported picture cropping; render the slide before rebuilding.")
    target = resolve_target(f"{posixpath.dirname(slide_part)}/_rels/{posixpath.basename(slide_part)}.rels", rel.attrib["Target"])
    return target, crop


def extract_image_based_pptx_pages(pptx_path, pages_dir):
    outputs = []
    with zipfile.ZipFile(pptx_path) as z:
        names = set(z.namelist())
        slide_cx, slide_cy = slide_size_from_pptx(z)
        for index, slide_part in enumerate(slide_parts_from_pptx(z), start=1):
            image_part, crop = full_slide_picture_target(z, slide_part, slide_cx, slide_cy)
            if image_part not in names:
                raise ValueError(f"{slide_part} references missing image part: {image_part}")
            page_dir = pages_dir / f"page_{index:03d}"
            page_dir.mkdir(parents=True, exist_ok=True)
            out = page_dir / "source.png"
            with Image.open(io.BytesIO(z.read(image_part))) as image:
                image = ImageOps.exif_transpose(image).convert("RGBA")
                if image.getchannel("A").getextrema()[0] != 255:
                    raise ValueError(f"{slide_part} has a transparent picture; render the slide before rebuilding.")
                image = image.convert("RGB")
                left, top, right, bottom = crop
                box = (image.width * left, image.height * top,
                       image.width * (1 - right), image.height * (1 - bottom))
                width = max(1, round(box[2] - box[0]))
                size = (width, max(1, round(width * slide_cy / slide_cx)))
                if any(crop) or size != image.size:
                    image = image.transform(size, Image.Transform.EXTENT, box,
                                            resample=Image.Resampling.BICUBIC)
                image.save(out)
            outputs.append(out)
    return outputs


def find_soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_office_to_pdf(input_path, out_dir):
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("No local Office converter is available for this input.")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(input_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pdfs = sorted(out_dir.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError(f"Office conversion did not produce a PDF in {out_dir}")
    return pdfs[0]


def convert_ppt_to_pptx(input_path, out_dir):
    if input_path.suffix.lower() == ".pptx":
        return input_path
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("No local Office converter is available to normalize .ppt input.")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pptx", "--outdir", str(out_dir), str(input_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pptxs = sorted(out_dir.glob("*.pptx"))
    if not pptxs:
        raise RuntimeError(f"Office conversion did not produce a PPTX in {out_dir}")
    return pptxs[0]


def page_record(job_dir, page_index, source, input_path, source_page):
    page_dir = source.parent
    rel_page_dir = page_dir.relative_to(job_dir).as_posix()
    return {
        "page_index": page_index,
        "source_page": source_page,
        "source_image": source.relative_to(job_dir).as_posix(),
        "page_dir": rel_page_dir,
        "manifest": f"{rel_page_dir}/manifest.json",
        "validation": f"{rel_page_dir}/validation.json",
        "input": Path(input_path).name,
        "agent_status": "pending",
    }


def default_job_dir(out_root, input_paths):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = Path(input_paths[0]).stem if input_paths else "job"
    return Path(out_root) / f"{stamp}-{stem}"


def default_output_name(input_paths):
    stem = Path(input_paths[0]).stem if input_paths else "deck"
    return f"{stem}_edited.pptx"


def normalize_inputs(inputs, out_root="output/image-to-editable-ppt", job_dir=None, dpi=180):
    """Prepare a new run without modifying an existing task or partial input set."""
    input_paths = [Path(path).expanduser().resolve() for path in inputs]
    if not input_paths or any(not path.is_file() for path in input_paths):
        raise ValueError("Prepare requires existing input files")
    target = Path(job_dir).expanduser() if job_dir else default_job_dir(out_root, input_paths)
    if target.is_symlink():
        raise ValueError("Prepare requires a new or empty task directory, not a symlink")
    target = target.resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"Task directory is not empty: {target}. Resume the existing run or choose a new --job-dir.")
    if any(path.is_relative_to(target) for path in input_paths):
        raise ValueError("Prepare inputs must be outside the new task directory")

    # Unsupported inputs and conversion failures never leave a half-prepared run.
    # Rename only a complete directory; rmdir refuses a destination populated by
    # another prepare/worker since the initial check.
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-prepare-", dir=target.parent) as temporary:
        stage = Path(temporary) / "run"
        deck_path = _normalize_inputs(input_paths, job_dir=stage, dpi=dpi)
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        deck["job_dir"] = str(target)
        deck_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            target.rmdir()
        stage.rename(target)
    return target / "deck_manifest.json"


def _normalize_inputs(inputs, out_root="output/image-to-editable-ppt", job_dir=None, dpi=180):
    input_paths = [Path(path).resolve() for path in inputs]
    job_dir = Path(job_dir).resolve() if job_dir else default_job_dir(out_root, input_paths).resolve()
    input_dir = job_dir / "input"
    pages_dir = job_dir / "pages"
    input_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    copied = [copy_input(path, input_dir) for path in input_paths]
    suffixes = {path.suffix.lower() for path in copied}
    pages = []
    notes = []
    source_slide = None
    input_type = "images"

    if len(copied) == 1 and copied[0].suffix.lower() == ".pdf":
        input_type = "pdf"
        sources = render_pdf_pages(copied[0], pages_dir, dpi)
        pages = [page_record(job_dir, i, source, copied[0], i) for i, source in enumerate(sources, start=1)]
    elif len(copied) == 1 and copied[0].suffix.lower() in PPT_EXTS:
        if copied[0].suffix.lower() == ".pptx":
            input_type = "pptx"
            notes = collect_notes_from_pptx(copied[0], input_dir / "notes")
            try:
                sources = extract_image_based_pptx_pages(copied[0], pages_dir)
            except ValueError as exc:
                raise SystemExit(
                    "Unsupported PPTX for the lightweight path: "
                    f"{exc} This skill accepts image-based PPTX files through lightweight extraction. "
                    "Convert native/complex PPTX slides to PDF or page images first."
                ) from exc
            with zipfile.ZipFile(copied[0]) as archive:
                width, height = slide_size_from_pptx(archive)
            source_slide = {"width": width / 914400, "height": height / 914400, "size_mode": "pptx"}
        else:
            input_type = "ppt"
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp)
                source_pptx = convert_ppt_to_pptx(copied[0], tmp_dir)
                with zipfile.ZipFile(source_pptx) as archive:
                    width, height = slide_size_from_pptx(archive)
                source_slide = {"width": width / 914400, "height": height / 914400, "size_mode": "pptx"}
                notes = collect_notes_from_pptx(source_pptx, input_dir / "notes")
                if source_pptx != copied[0]:
                    shutil.copy2(source_pptx, input_dir / source_pptx.name)
                rendered_pdf = convert_office_to_pdf(copied[0], tmp_dir)
                sources = render_pdf_pages(rendered_pdf, pages_dir, dpi)
        pages = [page_record(job_dir, i, source, copied[0], i) for i, source in enumerate(sources, start=1)]
    elif suffixes <= IMG_EXTS:
        input_type = "image" if len(copied) == 1 else "images"
        for i, src in enumerate(copied, start=1):
            source = save_image_page(src, pages_dir / f"page_{i:03d}")
            pages.append(page_record(job_dir, i, source, src, i))
    else:
        raise SystemExit(f"Unsupported input combination: {', '.join(str(path) for path in input_paths)}")

    for note in notes:
        notes_xml = note.get("notes_xml")
        if notes_xml:
            note["notes_xml"] = Path(notes_xml).relative_to(job_dir).as_posix()

    notes_manifest_path = job_dir / "notes_manifest.json"
    notes_manifest = {"source": copied[0].relative_to(job_dir).as_posix() if len(copied) == 1 else None, "notes": notes}
    notes_manifest_path.write_text(json.dumps(notes_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    deck_manifest = {
        "input_type": input_type,
        "job_dir": str(job_dir),
        "page_count": len(pages),
        "inputs": [path.relative_to(job_dir).as_posix() for path in copied],
        "pages": pages,
        "notes_manifest": notes_manifest_path.relative_to(job_dir).as_posix(),
        "output": default_output_name(copied),
        "validation": "validation.json",
    }
    if source_slide is not None:
        deck_manifest["source_slide"] = source_slide
    deck_manifest_path = job_dir / "deck_manifest.json"
    deck_manifest_path.write_text(json.dumps(deck_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return deck_manifest_path
