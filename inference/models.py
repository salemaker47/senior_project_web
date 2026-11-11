"""
inference/models.py

Mirror of `build_model` in the training repo (`src/sg_models.py`). The branch
list must stay identical to the training registry so that every checkpoint in
`model_store/` can be rebuilt. Add branches only; never change an existing one.

All models return raw logits of shape (N, 1, H, W).
"""

from __future__ import annotations

from typing import Any, Optional

import segmentation_models_pytorch as smp
import torch.nn as nn

# Human-readable labels for the registry's display strings.
ARCH_LABELS = {
    "smp_unet_resnet34":         "U-Net (ResNet34)",
    "smp_unet_resnet50":         "U-Net (ResNet50)",
    "smp_unetpp_efficientnetb4": "U-Net++ (EfficientNet-B4)",
    "smp_unetpp_resnet34":       "U-Net++ (ResNet34)",
    "smp_resunet_resnet34":      "Linknet (ResNet34)",
    "smp_manet_resnet34":        "MA-Net (ResNet34)",
}


def build_model(
    name: str = "smp_unet_resnet34",
    in_channels: int = 3,
    classes: int = 1,
    encoder_weights: Optional[str] = None,
    activation: Optional[str] = None,
    **extra_kwargs: Any,
) -> nn.Module:
    """
    Build a segmentation model by name. Same branches as the training repo.

    `encoder_weights` defaults to None here (the training repo defaults to
    "imagenet"): the web app always loads trained weights afterwards, and
    downloading ImageNet weights would be wasted work plus a network call.
    """
    common = {
        "in_channels":     in_channels,
        "classes":         classes,
        "encoder_weights": encoder_weights,
        "activation":      activation,
    }
    common.update(extra_kwargs)

    n = name.lower()

    if n == "smp_unet_resnet34":
        return smp.Unet(encoder_name="resnet34", **common)

    if n == "smp_unet_resnet50":
        return smp.Unet(encoder_name="resnet50", **common)

    if n == "smp_unetpp_efficientnetb4":
        return smp.UnetPlusPlus(encoder_name="efficientnet-b4", **common)

    if n == "smp_unetpp_resnet34":
        return smp.UnetPlusPlus(encoder_name="resnet34", **common)

    if n == "smp_resunet_resnet34":
        return smp.Linknet(encoder_name="resnet34", **common)

    if n == "smp_manet_resnet34":
        return smp.MAnet(encoder_name="resnet34", **common)

    raise ValueError(
        f"unknown model name: {name!r}. See inference/models.py (mirror of src/sg_models.py)."
    )
