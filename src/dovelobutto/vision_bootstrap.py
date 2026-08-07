from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .vision_corpus import split_for_capture_group, validate_vision_corpus, write_json


MASE_GUIDELINES_URL = (
    "https://www.etichetta-conai.com/wp-content/uploads/2021/02/"
    "Linee_guida_etichettatura_ambientale_27.09.2022.pdf"
)
MASE_DECREE_URL = (
    "https://www.mase.gov.it/sites/default/files/archivio/normativa/rifiuti/"
    "dm_360_28_09_2022.pdf"
)
MASE_LICENSE_URL = (
    "https://www.mase.gov.it/sites/default/files/archivio/allegati/vari/"
    "note_legali_privacy_minambiente.pdf"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capture_group_for_split(prefix: str, policy: dict[str, Any], split: str) -> str:
    for suffix in range(1000):
        candidate = f"{prefix}:{suffix}"
        if split_for_capture_group(candidate, policy) == split:
            return candidate
    raise ValueError(f"Could not allocate {prefix} to {split}")


def _image_metadata(
    path: Path,
    assets_root: Path,
    *,
    asset_id: str,
    source_id: str,
    capture_group_id: str,
    split: str,
    content_origin: str,
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    return {
        "asset_id": asset_id,
        "path": path.relative_to(assets_root).as_posix(),
        "sha256": _sha256(path),
        "mime_type": "image/png",
        "width": width,
        "height": height,
        "content_origin": content_origin,
        "source_id": source_id,
        "capture_group_id": capture_group_id,
        "split": split,
        "captured_at": None,
        "privacy_review": "approved",
        "annotations": annotations,
    }


def _render_reference_pages(
    guidelines_pdf: Path,
    assets_root: Path,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    from PIL import Image

    output_dir = assets_root / "reference" / "mase-guidelines-2022"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("pdftoppm is required to render the MASE reference pages")
    prefix = output_dir / "pdf-page"
    subprocess.run(
        [
            executable, "-f", "21", "-l", "40", "-r", "120", "-png",
            guidelines_pdf.as_posix(), prefix.as_posix(),
        ],
        check=True,
        capture_output=True,
    )
    assets = []
    for pdf_page in range(21, 41):
        document_page = pdf_page - 1
        rendered_source = output_dir / f"pdf-page-{pdf_page}.png"
        rendered = output_dir / f"page-{document_page:02d}.png"
        if not rendered_source.exists():
            raise ValueError(f"Rendered MASE PDF page {pdf_page} is missing")
        rendered_source.rename(rendered)
        with Image.open(rendered) as image:
            clean = image.convert("RGB")
            clean.save(rendered, format="PNG", optimize=True)
        group = _capture_group_for_split(
            f"mase-guidelines-page-{document_page}", policy, "train"
        )
        assets.append(
            _image_metadata(
                rendered,
                assets_root,
                asset_id=f"reference:mase-guidelines-2022:page-{document_page}",
                source_id="mase-guidelines-2022",
                capture_group_id=group,
                split="train",
                content_origin="document_crop",
                annotations=[],
            )
        )
    return assets


def _synthetic_label(entry: dict[str, Any], variant: int) -> str:
    if entry["abbreviation"]:
        abbreviation = entry["abbreviation"]
    else:
        options = {
            "paper_cardboard": ("C/PAP",),
            "plastic": ("C/PET", "C/HDPE", "C/LDPE", "C/PP"),
            "glass": ("C/GL",),
        }[entry["predominant_family"]]
        abbreviation = options[variant % len(options)]
    code = str(entry["numeric_code"])
    layouts = (
        f"{abbreviation} {code}",
        f"{code} {abbreviation}",
        f"{abbreviation}\n{code}",
        f">{abbreviation}< {code}",
        f"{abbreviation}  {code}",
        f"{abbreviation}\n{code}",
    )
    return layouts[variant]


def _generate_synthetic_marks(
    register: dict[str, Any],
    font_path: Path,
    assets_root: Path,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    output_dir = assets_root / "synthetic" / "eu-97-129-v1"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    assigned = [
        entry for entry in register["entries"]
        if entry["assignment_status"] == "assigned"
    ]
    for assigned_index, entry in enumerate(assigned):
        code = entry["numeric_code"]
        split = "validation" if assigned_index % 5 == 4 else "train"
        group = _capture_group_for_split(f"synthetic-eu-97-129-{code}", policy, split)
        for variant in range(6):
            width, height = 640, 360
            dark = variant == 4
            background = (31, 35, 38) if dark else (242 - variant * 8,) * 3
            foreground = (238, 240, 241) if dark else (25 + variant * 4,) * 3
            image = Image.new("RGB", (width, height), background)
            draw = ImageDraw.Draw(image)
            font_size = (104, 92, 106, 82, 98, 76)[variant]
            font = ImageFont.truetype(font_path.as_posix(), font_size)
            text = _synthetic_label(entry, variant)
            spacing = 2
            box = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
            text_width = box[2] - box[0]
            text_height = box[3] - box[1]
            x = (width - text_width) // 2
            y = (height - text_height) // 2 - box[1]
            if variant in (3, 4):
                padding = 28
                draw.rectangle(
                    (x - padding, y + box[1] - padding, x + text_width + padding, y + box[3] + padding),
                    outline=foreground,
                    width=5 if variant == 4 else 3,
                )
            draw.multiline_text((x, y), text, fill=foreground, font=font, spacing=spacing, align="center")
            if variant == 5:
                glare = Image.new("RGBA", image.size, (0, 0, 0, 0))
                glare_draw = ImageDraw.Draw(glare)
                glare_draw.polygon(
                    [(360, 0), (500, 0), (300, height), (170, height)],
                    fill=(255, 255, 255, 72),
                )
                image = Image.alpha_composite(image.convert("RGBA"), glare).convert("RGB")
                image = image.filter(ImageFilter.GaussianBlur(radius=0.7))
            path = output_dir / f"code-{code:02d}-variant-{variant + 1}.png"
            image.save(path, format="PNG", optimize=True)
            padding = 32 if variant in (3, 4) else 8
            x_min = max(0, x - padding) / width
            y_min = max(0, y + box[1] - padding) / height
            x_max = min(width, x + text_width + padding) / width
            y_max = min(height, y + box[3] + padding) / height
            annotation = {
                "annotation_id": f"synthetic:eu-97-129:{code}:v{variant + 1}:mark",
                "category_id": "mark.material_identification",
                "bounding_box": {
                    "x_min": round(x_min, 6), "y_min": round(y_min, 6),
                    "x_max": round(x_max, 6), "y_max": round(y_max, 6),
                },
                "transcription": " ".join(text.split()),
                "transcription_status": "exact",
                "resolved_mark_ref": entry["mark_id"],
                "quality": {
                    "occlusion": "none",
                    "blur": "moderate" if variant == 5 else "none",
                    "glare": "moderate" if variant == 5 else "none",
                    "perspective": "frontal",
                },
            }
            assets.append(
                _image_metadata(
                    path,
                    assets_root,
                    asset_id=f"synthetic:eu-97-129:{code}:v{variant + 1}",
                    source_id="comesibutta-synthetic-v1",
                    capture_group_id=group,
                    split=split,
                    content_origin="synthetic",
                    annotations=[annotation],
                )
            )
    return assets


def build_vision_bootstrap(
    register_path: Path,
    taxonomy_path: Path,
    guidelines_pdf: Path,
    decree_pdf: Path,
    legal_notice_pdf: Path,
    font_path: Path,
    assets_root: Path,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    register = json.loads(register_path.read_text(encoding="utf-8"))
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    policy = {
        "unit": "capture_group",
        "algorithm": "sha256_mod_100",
        "seed": "comesibutta-vision-v1",
        "train": [0, 79],
        "validation": [80, 89],
        "test": [90, 99],
    }
    assets = _render_reference_pages(guidelines_pdf, assets_root, policy)
    assets.extend(_generate_synthetic_marks(register, font_path, assets_root, policy))
    manifest = {
        "version": 1,
        "corpus_id": "comesibutta-packaging-marks",
        "corpus_version": "0.2.0-bootstrap",
        "created_at": generated_at.isoformat(),
        "taxonomy": {
            "taxonomy_id": taxonomy["taxonomy_id"],
            "taxonomy_version": taxonomy["taxonomy_version"],
            "sha256": _sha256(taxonomy_path),
        },
        "split_policy": policy,
        "sources": [
            {
                "source_id": "mase-guidelines-2022",
                "rights_basis": "open_license",
                "license_id": "CC-BY-4.0",
                "license_url": MASE_LICENSE_URL,
                "attribution": "Ministero dell'Ambiente e della Sicurezza Energetica",
                "rights_review": "approved",
                "personal_data_allowed": False,
                "notes": (
                    f"Allegato tecnico adottato dal DM 360/2022 ({MASE_DECREE_URL}); "
                    f"copia integrale pubblicata da CONAI ({MASE_GUIDELINES_URL}). "
                    f"PDF { _sha256(guidelines_pdf) }; decreto { _sha256(decree_pdf) }; "
                    f"note legali { _sha256(legal_notice_pdf) }."
                ),
            },
            {
                "source_id": "comesibutta-synthetic-v1",
                "rights_basis": "original_work",
                "license_id": None,
                "license_url": None,
                "attribution": "ComeSiButta",
                "rights_review": "approved",
                "personal_data_allowed": False,
                "notes": (
                    "Varianti generate dai dati normativi con Noto Sans, distribuito "
                    "secondo SIL Open Font License 1.1."
                ),
            },
        ],
        "assets": assets,
    }
    temporary_manifest = assets_root.parent / ".vision-bootstrap-manifest.tmp.json"
    write_json(temporary_manifest, manifest)
    try:
        report = validate_vision_corpus(temporary_manifest, taxonomy_path, assets_root)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    report["reference_pages"] = 20
    report["synthetic_variants"] = len(assets) - 20
    report["font_sha256"] = _sha256(font_path)
    report["source_sha256"] = {
        "guidelines_pdf": _sha256(guidelines_pdf),
        "decree_pdf": _sha256(decree_pdf),
        "legal_notice_pdf": _sha256(legal_notice_pdf),
    }
    return manifest, report
