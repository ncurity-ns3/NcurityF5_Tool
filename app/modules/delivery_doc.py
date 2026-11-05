"""Generate delivery confirmation Word documents from the template."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from app.runtime.paths import output_dir, template_path

_SN_FULL = re.compile(r"^F5-[A-Z0-9]{4}-[A-Z0-9]{4}$")

_APPLIANCE_SPECS_SMALL = """•Interface :
- 1G/10G RJ45 Ports : 4EA
- 1G/10G/25G (SFP/SFP+/SFP28) Ports : 4EA
•Dimension : 1U (4.37H x 44.2W x 42.9D)
•PSU : 2 x 250 W 100-240 VAC ( +/- 10% ) Auto Switching Platinum"""

_APPLIANCE_SPECS_MID = """•Interface :
- 10G/25G (SFP+/SFP28) Ports : 8EA
- 40G/100G (QSFP28/QSFP+) Ports : 2EA
•Dimension : 1U (4.37H x 44.2W x 77.7D)
•PSU : 650 W 100-240 VAC (+/- 10%) AUTO Switching Platinum"""

_APPLIANCE_SPECS_LARGE = """•Interface :
- 10G/25G (SFP+/SFP28) Ports : 8EA
- 40G/100G (QSFP28/QSFP+) Ports : 2EA
•Dimension : 1U (4.37H x 44.2W x 77.7D)
•PSU : 2 x 1200 W 100-240 VAC (+/- 10%) AUTO Switching Platinum"""

_GBIC_MODEL_LABELS = {
    "Multi 1G UTP ( RJ45 )": "1G UTP",
    "Multi 1G Fiber ( LC )": "1G Fiber GBIC",
    "Multi 10G Fiber ( LC )": "10G Fiber GBIC",
    "Multi 25G Fiber ( LC )": "25G Fiber GBIC",
    "Multi 40G Fiber ( MPO )": "40G Fiber GBIC",
    "Multi 40G Fiber ( BiDi, LC )": "40G Fiber BiDi GBIC",
    "Multi 100G Fiber ( MPO )": "100G Fiber GBIC",
    "Multi 100G Fiber ( Bidi, LC )": "100G Fiber BiDi GBIC",
    "Single 1G Fiber": "Single 1G Fiber GBIC",
    "Single 10G Fiber": "Single 10G Fiber GBIC",
}


@dataclass
class ProductItem:
    classification: str  # Appliance | Virtual Edition
    device: str
    ve_version: str
    ve_license: str
    quantity: int
    serial_numbers: list[str] = field(default_factory=list)
    license_keys: list[str] = field(default_factory=list)


@dataclass
class DeliveryFormData:
    doc_no: str
    author: str
    doc_date: str
    customer: str
    solution: str
    delivery_place: str
    products: list[ProductItem]
    license_name: str
    add_on: str
    add_on_detail: str
    # [("Multi 10G Fiber ( LC )", 10), ...] — empty when None
    gbic_items: list[tuple[str, int]]


def format_sn_input(raw: str) -> str:
    """Normalize typed input to F5-XXXX-XXXX (uppercase, auto dashes)."""
    chars = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if chars.startswith("F5"):
        chars = chars[2:]
    chars = chars[:8]
    if not chars:
        return ""
    if len(chars) <= 4:
        return f"F5-{chars}"
    return f"F5-{chars[:4]}-{chars[4:]}"


def format_sn_with_cursor(raw: str, cursor: int) -> tuple[str, int]:
    """Format S/N and map cursor to the same body-character offset."""
    before = raw[: max(0, cursor)]
    body_before = re.sub(r"[^A-Za-z0-9]", "", before).upper()
    if body_before.startswith("F5"):
        body_count = len(body_before) - 2
    else:
        body_count = len(body_before)
    body_count = max(0, min(8, body_count))

    formatted = format_sn_input(raw)
    if not formatted:
        return "", 0
    # F5-XXXX-XXXX → after N body chars
    if body_count <= 4:
        new_pos = 3 + body_count
    else:
        new_pos = 8 + (body_count - 4)
    return formatted, min(new_pos, len(formatted))


def is_complete_sn(value: str) -> bool:
    return bool(_SN_FULL.match(value.strip().upper()))


def ve_speed_code(ve_license: str) -> str:
    """1Gbps -> 1G, 10Mbps -> 10M, 200Mbps -> 200M."""
    text = ve_license.strip()
    text = re.sub(r"bps$", "", text, flags=re.IGNORECASE)
    return text


def build_ve_license_sku(license_name: str, ve_license: str, ve_version: str) -> str:
    speed = ve_speed_code(ve_license)
    version = ve_version.strip() or "V23"
    return f"F5-BIG-{license_name}-VE-{speed}-{version}"


def format_addon_display(add_on: str, add_on_detail: str) -> str:
    if not add_on or add_on == "None":
        return ""
    if add_on == "CCU":
        return add_on_detail.strip()
    if add_on in ("URL Filter", "SWG"):
        return f"{add_on} {add_on_detail}".strip()
    return add_on


def _appliance_body_specs(device: str) -> str:
    model = device.upper().replace("BIG-IP ", "").strip()
    # r2600 / r2800 / r4600 / r4800
    if any(x in model for x in ("R2600", "R2800", "R4600", "R4800")):
        return _APPLIANCE_SPECS_SMALL
    # r10600 / r10800 / r10900
    if any(x in model for x in ("R10600", "R10800", "R10900")):
        return _APPLIANCE_SPECS_LARGE
    # r5600 / r5800 / r5900 (default mid)
    return _APPLIANCE_SPECS_MID


def build_product_spec(
    product: ProductItem,
    data: DeliveryFormData,
    *,
    include_addon: bool = True,
) -> str:
    lines: list[str] = []
    if product.classification == "Appliance":
        sns = [s for s in product.serial_numbers if s.strip()]
        if sns:
            lines.append("•S/N : " + " / ".join(sns))
        lines.append(_appliance_body_specs(product.device))
    else:
        lines.append("F5 VE License")
        lines.append(
            build_ve_license_sku(data.license_name, product.ve_license, product.ve_version)
        )
        if product.license_keys:
            keys = [k.strip().upper() for k in product.license_keys if k.strip()]
            if keys:
                lines.append("•License Key : " + " / ".join(keys))

    if include_addon:
        addon = format_addon_display(data.add_on, data.add_on_detail)
        if addon:
            lines.append(f"Add-On License : {addon}")
    return "\n".join(lines)


def gbic_model_label(full_name: str) -> str:
    return _GBIC_MODEL_LABELS.get(full_name, full_name)


def build_gbic_spec(full_name: str) -> str:
    return f"•Type : {full_name}"


def format_gbic_lines(items: list[tuple[str, int]]) -> list[str]:
    return [f"{name} | {qty} EA" for name, qty in items]


def _set_cell_text(cell, text: str) -> None:
    """Replace cell text while keeping the first run's formatting when possible."""
    paragraphs = cell.paragraphs
    if not paragraphs:
        return
    first = paragraphs[0]
    if first.runs:
        first.runs[0].text = text
        for run in first.runs[1:]:
            run.text = ""
    else:
        first.add_run(text)
    for para in paragraphs[1:]:
        for run in para.runs:
            run.text = ""


def _apply_run_font(run, font_pt: float) -> None:
    run.font.size = Pt(font_pt)


def _set_paragraph_align(paragraph, align: WD_ALIGN_PARAGRAPH) -> None:
    paragraph.alignment = align


def _set_cell_vertical_center(cell) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _set_cell_multiline(
    cell,
    text: str,
    *,
    font_pt: float | None = None,
    align_center: bool = False,
) -> None:
    """Write multi-line text into a table cell."""
    lines = text.split("\n") if text else [""]
    for p in cell.paragraphs[1:]:
        element = p._element
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)

    first = cell.paragraphs[0]
    if first.runs:
        first.runs[0].text = lines[0]
        for run in first.runs[1:]:
            run.text = ""
        if font_pt is not None:
            _apply_run_font(first.runs[0], font_pt)
    else:
        run = first.add_run(lines[0])
        if font_pt is not None:
            _apply_run_font(run, font_pt)

    if align_center:
        _set_paragraph_align(first, WD_ALIGN_PARAGRAPH.CENTER)

    for line in lines[1:]:
        para = cell.add_paragraph()
        run = para.add_run(line)
        if font_pt is not None:
            _apply_run_font(run, font_pt)
        if align_center:
            _set_paragraph_align(para, WD_ALIGN_PARAGRAPH.CENTER)

    if align_center:
        _set_cell_vertical_center(cell)


def _add_word_field(paragraph, instruction: str, placeholder: str = "1") -> None:
    """Insert a Word field (e.g. PAGE, NUMPAGES) into a paragraph."""

    def _append_fld_char(fld_type: str) -> None:
        run = paragraph.add_run()
        fld = OxmlElement("w:fldChar")
        fld.set(qn("w:fldCharType"), fld_type)
        run._r.append(fld)

    _append_fld_char("begin")

    instr_run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    instr_run._r.append(instr)

    _append_fld_char("separate")
    paragraph.add_run(placeholder)
    _append_fld_char("end")


def _apply_page_number_fields(doc: Document) -> None:
    """Header 페이지번호 cell → PAGE/NUMPAGES (1/2, 2/2, ...)."""
    header = doc.sections[0].header
    if not header.tables:
        return
    cell = header.tables[0].rows[1].cells[3]
    # Clear existing content
    for p in cell.paragraphs[1:]:
        el = p._element
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    para = cell.paragraphs[0]
    for run in para.runs:
        run.text = ""
    # Remove leftover runs
    for child in list(para._p):
        if child.tag.endswith("}r"):
            para._p.remove(child)

    _add_word_field(para, "PAGE", "1")
    slash = para.add_run("/")
    slash.font.size = Pt(9)
    _add_word_field(para, "NUMPAGES", "1")

def _filename_date(doc_date: str) -> str:
    digits = re.sub(r"\D", "", doc_date)
    if len(digits) >= 8:
        return digits[2:8]
    if len(digits) == 6:
        return digits
    return digits or "000000"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ._") or "untitled"


def build_output_filename(data: DeliveryFormData) -> str:
    date_part = _filename_date(data.doc_date)
    customer = _safe_name(data.customer)
    solution = _safe_name(data.solution)
    return f"{date_part}_납품확인서_{customer}_{solution}.docx"


def _apply_header(doc: Document, data: DeliveryFormData) -> None:
    header = doc.sections[0].header
    if not header.tables:
        return
    table = header.tables[0]
    _set_cell_text(table.rows[0].cells[3], data.doc_no)
    _set_cell_text(table.rows[2].cells[3], data.author)
    _set_cell_text(table.rows[3].cells[3], data.doc_date)


def _apply_delivery_place(doc: Document, place: str) -> None:
    if not doc.tables:
        return
    row = doc.tables[0].rows[3]
    for ci in (2, 3, 4):
        _set_cell_text(row.cells[ci], place)


def _reset_acceptance_fields(doc: Document) -> None:
    """Clear 인수일자 value; keep 회사명 label with blank value for handwriting."""
    if len(doc.tables) < 3:
        return
    cell = doc.tables[2].rows[0].cells[0]
    for para in cell.paragraphs:
        text = para.text
        if text.startswith("인수일자"):
            if para.runs:
                para.runs[0].text = "인수일자 :"
                for run in para.runs[1:]:
                    run.text = ""
            else:
                para.add_run("인수일자 :")
        elif "사 명" in text or text.startswith("회 사"):
            if para.runs:
                para.runs[0].text = "회 사 명 :"
                for run in para.runs[1:]:
                    run.text = ""
            else:
                para.add_run("회 사 명 :")


def _ensure_data_rows(table, needed: int) -> None:
    """Ensure table has header + needed data rows (clone last row XML)."""
    while len(table.rows) - 1 < needed:
        tbl = table._tbl
        last_tr = table.rows[-1]._tr
        tbl.append(deepcopy(last_tr))


def _clear_row(row) -> None:
    for cell in row.cells:
        _set_cell_multiline(cell, "")


def _fill_items_table(doc: Document, data: DeliveryFormData) -> None:
    if len(doc.tables) < 2:
        return
    table = doc.tables[1]
    rows_data: list[tuple[str, str, str, str]] = []

    category = f"F5 BIG-IP\n{data.solution}"
    for idx, product in enumerate(data.products):
        if product.classification == "Appliance":
            model = product.device
        else:
            model = "BIG-IP Virtual Edition"
        # Add-On은 첫 제품 사양에만 기재 (중복 방지)
        spec = build_product_spec(product, data, include_addon=(idx == 0))
        qty = f"{product.quantity} 식"
        rows_data.append((category, model, spec, qty))

    for full_name, qty in data.gbic_items:
        rows_data.append(
            (
                "광 모듈",
                gbic_model_label(full_name),
                build_gbic_spec(full_name),
                f"{qty} EA",
            )
        )

    needed = max(len(rows_data), 1)
    _ensure_data_rows(table, needed)

    # Fill data rows (skip header at index 0)
    for i, (cat, model, spec, qty) in enumerate(rows_data):
        row = table.rows[i + 1]
        _set_cell_multiline(row.cells[0], cat, font_pt=8, align_center=True)
        _set_cell_multiline(row.cells[1], model, font_pt=8, align_center=True)
        _set_cell_multiline(row.cells[2], spec, font_pt=8)
        _set_cell_multiline(row.cells[3], qty, font_pt=8, align_center=True)
        # 세로 가운데는 분류/모델 외 수량에도 적용
        _set_cell_vertical_center(row.cells[2])
        _set_cell_vertical_center(row.cells[3])

    # Clear leftover template rows
    for i in range(len(rows_data) + 1, len(table.rows)):
        _clear_row(table.rows[i])


def _keep_acceptance_table_together(doc: Document) -> None:
    """
    마지막 인수 확인 표가 페이지 중간에서 잘리지 않도록 통째로 다음 페이지로 넘김.
    - 행 분할 금지(cantSplit)
    - 셀 안 문단 keepNext/keepLines로 내용 묶기
    """
    if len(doc.tables) < 3:
        return
    table = doc.tables[2]
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        for el in tr_pr.findall(qn("w:cantSplit")):
            tr_pr.remove(el)
        tr_pr.append(OxmlElement("w:cantSplit"))

        for cell in row.cells:
            paras = cell.paragraphs
            for para in paras:
                p_pr = para._p.get_or_add_pPr()
                for tag in ("w:keepLines", "w:keepNext"):
                    for el in p_pr.findall(qn(tag)):
                        p_pr.remove(el)
                p_pr.append(OxmlElement("w:keepLines"))
            # 마지막 문단 제외하고 keepNext → 표 내용이 한 덩어리로 유지
            for para in paras[:-1]:
                p_pr = para._p.get_or_add_pPr()
                p_pr.append(OxmlElement("w:keepNext"))


def _disable_update_fields_on_open(doc: Document) -> None:
    """Remove updateFields so Word does not prompt on open."""
    settings = doc.settings.element
    for child in list(settings):
        if child.tag.endswith("}updateFields"):
            settings.remove(child)


def _strip_external_style_refs(doc: Document) -> None:
    """Clear bibliography SelectedStyle paths that can trigger the linked-field dialog."""
    package = doc.part.package
    for part in package.parts:
        name = str(getattr(part, "partname", "") or "")
        if "customXml" not in name.replace("\\", "/"):
            continue
        try:
            blob = part.blob
        except Exception:  # noqa: BLE001
            continue
        if not blob or b"SelectedStyle" not in blob:
            continue
        text = blob.decode("utf-8", errors="ignore")
        if "SelectedStyle=" not in text:
            continue
        cleaned = re.sub(
            r'\sSelectedStyle="[^"]*"',
            ' SelectedStyle=""',
            text,
            count=1,
        )
        if cleaned != text:
            part._blob = cleaned.encode("utf-8")


def generate_delivery_confirmation(
    data: DeliveryFormData,
    *,
    out_dir: Path | None = None,
) -> Path:
    tpl = template_path()
    if not tpl.is_file():
        raise FileNotFoundError(f"템플릿을 찾을 수 없습니다: {tpl}")

    doc = Document(str(tpl))
    _apply_header(doc, data)
    _apply_page_number_fields(doc)
    _apply_delivery_place(doc, data.delivery_place)
    _reset_acceptance_fields(doc)
    _keep_acceptance_table_together(doc)
    _fill_items_table(doc, data)
    _strip_external_style_refs(doc)
    # Last: never leave updateFields on (PAGE fields stay; Word won't prompt).
    _disable_update_fields_on_open(doc)

    target_dir = out_dir or output_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / build_output_filename(data)
    doc.save(str(out_path))
    return out_path
