from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import time
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision.models import MobileNet_V3_Large_Weights
from torchvision.models.detection import ssdlite320_mobilenet_v3_large
from torchvision.transforms import functional as F


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


class PackagingMarkDataset(Dataset):
    def __init__(
        self,
        manifest: dict[str, Any],
        assets_root: Path,
        category_labels: dict[str, int],
        split: str,
        augment: bool,
        seed: int,
    ) -> None:
        self.assets = [
            asset for asset in manifest["assets"]
            if asset["split"] == split and asset["annotations"]
        ]
        self.assets_root = assets_root
        self.category_labels = category_labels
        self.augment = augment
        self.seed = seed

    def __len__(self) -> int:
        return len(self.assets)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        asset = self.assets[index]
        path = self.assets_root / asset["path"]
        with Image.open(path) as source:
            image = source.convert("RGB")
        if self.augment:
            generator = random.Random(f"{self.seed}:{asset['asset_id']}")
            image = ImageEnhance.Brightness(image).enhance(generator.uniform(0.75, 1.2))
            image = ImageEnhance.Contrast(image).enhance(generator.uniform(0.75, 1.25))
            if generator.random() < 0.35:
                image = image.filter(ImageFilter.GaussianBlur(generator.uniform(0.2, 1.1)))
        width, height = image.size
        boxes = []
        labels = []
        for annotation in asset["annotations"]:
            box = annotation["bounding_box"]
            boxes.append([
                box["x_min"] * width,
                box["y_min"] * height,
                box["x_max"] * width,
                box["y_max"] * height,
            ])
            labels.append(self.category_labels[annotation["category_id"]])
        target = {
            "boxes": torch.tensor(boxes, dtype=torch.float32),
            "labels": torch.tensor(labels, dtype=torch.int64),
            "image_id": torch.tensor(index, dtype=torch.int64),
        }
        return F.pil_to_tensor(image).float().div(255), target


def _collate(batch: list[Any]) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    return tuple(zip(*batch))


def _box_iou(first: torch.Tensor, second: torch.Tensor) -> float:
    left = max(float(first[0]), float(second[0]))
    top = max(float(first[1]), float(second[1]))
    right = min(float(first[2]), float(second[2]))
    bottom = min(float(first[3]), float(second[3]))
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, float(first[2] - first[0])) * max(
        0.0, float(first[3] - first[1])
    )
    second_area = max(0.0, float(second[2] - second[0])) * max(
        0.0, float(second[3] - second[1])
    )
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _evaluate(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    score_threshold: float = 0.3,
) -> dict[str, float | int]:
    model.eval()
    records = []
    with torch.inference_mode():
        for images, targets in loader:
            predictions = model([image.to(device) for image in images])
            records.extend(
                (prediction, target)
                for prediction, target in zip(predictions, targets)
            )
    return _metrics_from_records(records, score_threshold)


def _metrics_from_records(
    records: list[tuple[dict[str, torch.Tensor], dict[str, torch.Tensor]]],
    score_threshold: float,
) -> dict[str, float | int]:
    true_positives = 0
    false_positives = 0
    ground_truth = 0
    best_ious = []
    best_scores = []
    for prediction, target in records:
        target_boxes = target["boxes"]
        target_labels = target["labels"]
        ground_truth += len(target_boxes)
        used_predictions: set[int] = set()
        for target_box, target_label in zip(target_boxes, target_labels):
            candidates = [
                index for index, (score, label) in enumerate(
                    zip(prediction["scores"], prediction["labels"])
                )
                if float(score) >= score_threshold
                and int(label) == int(target_label)
                and index not in used_predictions
            ]
            if not candidates:
                best_ious.append(0.0)
                best_scores.append(0.0)
                continue
            scored = [
                (_box_iou(prediction["boxes"][index].cpu(), target_box), index)
                for index in candidates
            ]
            best_iou, best_index = max(scored)
            best_ious.append(best_iou)
            best_scores.append(float(prediction["scores"][best_index]))
            if best_iou >= 0.5:
                true_positives += 1
                used_predictions.add(best_index)
        false_positives += sum(
            float(score) >= score_threshold and index not in used_predictions
            for index, score in enumerate(prediction["scores"])
        )
    precision = true_positives / (true_positives + false_positives) if (
        true_positives + false_positives
    ) else 0.0
    recall = true_positives / ground_truth if ground_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "ground_truth": ground_truth,
        "true_positives_iou_50": true_positives,
        "false_positives": false_positives,
        "precision_iou_50": round(precision, 6),
        "recall_iou_50": round(recall, 6),
        "f1_iou_50": round(f1, 6),
        "mean_best_iou": round(statistics.fmean(best_ious), 6) if best_ious else 0.0,
        "mean_best_score": round(statistics.fmean(best_scores), 6) if best_scores else 0.0,
        "score_threshold": score_threshold,
    }


def train_vision_bootstrap(
    manifest_path: Path,
    taxonomy_path: Path,
    assets_root: Path,
    output_dir: Path,
    generated_at: datetime,
    *,
    epochs: int = 3,
    batch_size: int = 4,
    learning_rate: float = 0.001,
    seed: int = 20260807,
    device_name: str = "cpu",
) -> dict[str, Any]:
    if epochs < 1 or batch_size < 1:
        raise ValueError("Epochs and batch size must be positive")
    if device_name != "cpu":
        raise ValueError("The bootstrap trainer currently supports the CPU device only")
    _seed_everything(seed)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    category_labels = {
        item["category_id"]: item["detector_index"] + 1
        for item in taxonomy["classes"]
    }
    train_dataset = PackagingMarkDataset(
        manifest, assets_root, category_labels, "train", True, seed,
    )
    validation_dataset = PackagingMarkDataset(
        manifest, assets_root, category_labels, "validation", False, seed,
    )
    if not train_dataset or not validation_dataset:
        raise ValueError("Bootstrap training requires annotated train and validation assets")
    generator = torch.Generator().manual_seed(seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
        collate_fn=_collate,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=1,
        shuffle=False,
        num_workers=0,
        collate_fn=_collate,
    )
    device = torch.device(device_name)
    model = ssdlite320_mobilenet_v3_large(
        weights=None,
        weights_backbone=MobileNet_V3_Large_Weights.IMAGENET1K_V2,
        num_classes=len(category_labels) + 1,
        trainable_backbone_layers=0,
    ).to(device)
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=learning_rate, weight_decay=0.0001)
    history = []
    started = time.monotonic()
    baseline = _evaluate(model, validation_loader, device)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "model.pt"
    best_key = (-1.0, -1.0)
    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        components: Counter[str] = Counter()
        for images, targets in train_loader:
            images_on_device = [image.to(device) for image in images]
            targets_on_device = [
                {key: value.to(device) for key, value in target.items()}
                for target in targets
            ]
            loss_parts = model(images_on_device, targets_on_device)
            loss = sum(loss_parts.values())
            if not torch.isfinite(loss):
                raise ValueError(f"Non-finite training loss at epoch {epoch}")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, max_norm=5.0)
            optimizer.step()
            losses.append(float(loss.detach()))
            for name, value in loss_parts.items():
                components[name] += float(value.detach())
        metrics = _evaluate(model, validation_loader, device)
        epoch_report = {
            "epoch": epoch,
            "mean_train_loss": round(statistics.fmean(losses), 6),
            "mean_loss_components": {
                name: round(total / len(losses), 6)
                for name, total in sorted(components.items())
            },
            "validation": metrics,
        }
        history.append(epoch_report)
        metric_key = (
            float(metrics["f1_iou_50"]),
            float(metrics["mean_best_iou"]),
        )
        if metric_key > best_key:
            best_key = metric_key
            torch.save(
                {
                    "architecture": "torchvision-ssdlite320-mobilenet-v3-large",
                    "model_version": "0.1.0-bootstrap",
                    "taxonomy_version": taxonomy["taxonomy_version"],
                    "category_labels": category_labels,
                    "manifest_sha256": _sha256(manifest_path),
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                },
                checkpoint_path,
            )
    elapsed = time.monotonic() - started
    report = {
        "generated_at": generated_at.isoformat(),
        "status": "bootstrap_not_for_release",
        "architecture": "torchvision-ssdlite320-mobilenet-v3-large",
        "model_version": "0.1.0-bootstrap",
        "taxonomy_version": taxonomy["taxonomy_version"],
        "manifest_sha256": _sha256(manifest_path),
        "checkpoint": {
            "path": checkpoint_path.as_posix(),
            "sha256": _sha256(checkpoint_path),
            "bytes": checkpoint_path.stat().st_size,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "torchvision": __import__("torchvision").__version__,
            "device": str(device),
        },
        "configuration": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "seed": seed,
            "pretrained_backbone": "MobileNet_V3_Large_Weights.IMAGENET1K_V2",
            "frozen_backbone": True,
        },
        "dataset": {
            "annotated_train_assets": len(train_dataset),
            "annotated_validation_assets": len(validation_dataset),
            "excluded_unannotated_assets": sum(
                not asset["annotations"] for asset in manifest["assets"]
            ),
            "observed_categories": sorted({
                annotation["category_id"]
                for asset in manifest["assets"]
                for annotation in asset["annotations"]
            }),
        },
        "baseline_validation": baseline,
        "epochs": history,
        "best_epoch": max(
            history,
            key=lambda item: (
                item["validation"]["f1_iou_50"],
                item["validation"]["mean_best_iou"],
            ),
        )["epoch"],
        "elapsed_seconds": round(elapsed, 3),
        "limitations": [
            "Only synthetic material-identification marks are annotated.",
            "No real photographs are present in validation or test.",
            "The checkpoint must not be distributed as a release model.",
        ],
    }
    _write_json(output_dir / "training-report.json", report)
    return report


def evaluate_vision_checkpoint(
    checkpoint_path: Path,
    manifest_path: Path,
    taxonomy_path: Path,
    assets_root: Path,
    output_dir: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    from PIL import ImageDraw, ImageFont

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    category_labels = checkpoint["category_labels"]
    dataset = PackagingMarkDataset(
        manifest, assets_root, category_labels, "validation", False, 0,
    )
    loader = DataLoader(
        dataset, batch_size=1, shuffle=False, num_workers=0, collate_fn=_collate,
    )
    model = ssdlite320_mobilenet_v3_large(
        weights=None,
        weights_backbone=MobileNet_V3_Large_Weights.IMAGENET1K_V2,
        num_classes=len(category_labels) + 1,
        trainable_backbone_layers=0,
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    records = []
    images_for_preview = []
    with torch.inference_mode():
        for images, targets in loader:
            prediction = model([images[0]])[0]
            records.append((prediction, targets[0]))
            images_for_preview.append(images[0])
    thresholds = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
    sweep = {
        f"{threshold:.1f}": _metrics_from_records(records, threshold)
        for threshold in thresholds
    }
    selected_threshold = max(
        thresholds,
        key=lambda threshold: (
            sweep[f"{threshold:.1f}"]["f1_iou_50"],
            sweep[f"{threshold:.1f}"]["precision_iou_50"],
        ),
    )
    tile_width, tile_height = 320, 210
    preview = Image.new("RGB", (tile_width * 3, tile_height * 4), "white")
    font = ImageFont.load_default(size=14)
    for tile_index, ((prediction, target), tensor) in enumerate(
        zip(records[:12], images_for_preview[:12])
    ):
        image = F.to_pil_image(tensor).convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in target["boxes"]:
            draw.rectangle(tuple(float(value) for value in box), outline="#18864B", width=5)
        kept = [
            index for index, score in enumerate(prediction["scores"])
            if float(score) >= selected_threshold
        ][:5]
        for index in kept:
            box = prediction["boxes"][index]
            draw.rectangle(tuple(float(value) for value in box), outline="#D83B32", width=4)
        image.thumbnail((tile_width, tile_height - 30))
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        tile.paste(image, ((tile_width - image.width) // 2, 0))
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.text(
            (8, tile_height - 24),
            f"GT verde | pred rosso | soglia {selected_threshold:.1f}",
            fill="#20272A",
            font=font,
        )
        preview.paste(
            tile,
            ((tile_index % 3) * tile_width, (tile_index // 3) * tile_height),
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / "validation-preview.png"
    preview.save(preview_path, optimize=True)
    report = {
        "generated_at": generated_at.isoformat(),
        "status": "synthetic_validation_only",
        "model_version": checkpoint["model_version"],
        "taxonomy_version": taxonomy["taxonomy_version"],
        "checkpoint_sha256": _sha256(checkpoint_path),
        "validation_assets": len(dataset),
        "threshold_sweep": sweep,
        "selected_threshold": selected_threshold,
        "selection_rule": "highest F1 at IoU 0.5, then highest precision",
        "preview": {
            "path": preview_path.as_posix(),
            "sha256": _sha256(preview_path),
            "samples": min(12, len(dataset)),
        },
        "release_eligible": False,
    }
    _write_json(output_dir / "evaluation-report.json", report)
    return report
