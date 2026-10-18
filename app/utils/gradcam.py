"""
app/utils/gradcam.py

Grad-CAM for the DenseNet-121 pneumonia model (single logit output).
Same maths and same look as the notebook's generate_gradcam(), but:
  - no matplotlib / no files on disk (returns an image in memory)
  - no backward pass through the network (much faster on CPU)

Only needs: torch, numpy, PIL.
"""
import base64
import io

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


def grad_cam(model, image_tensor):
    """
    model        : trained DenseNet-121 (loaded, any mode)
    image_tensor : (1, 3, 224, 224), preprocessed exactly like val/test
    returns      : (pneumonia_probability, cam)  cam is (224, 224), values 0..1

    Why no backward pass: DenseNet ends with  ReLU -> average pool -> Linear.
    For that ending, the gradient Grad-CAM would compute for channel c is
        classifier_weight[c] * (share of positions where channel c is active)
    (the constant 1/(H*W) cancels after normalising), so we can write it down
    directly. This matches the hook-based version (gradient at model.features).
    """
    model.eval()
    with torch.inference_mode():
        feats = model.features(image_tensor)                   # (1, 1024, 7, 7), before ReLU
        acts = F.relu(feats)
        pooled = F.adaptive_avg_pool2d(acts, (1, 1)).flatten(1)
        logit = model.classifier(pooled)                       # (1, 1)

        w = model.classifier.weight[0]                         # (1024,)
        active_share = (feats > 0).float().mean(dim=(2, 3))[0]  # (1024,)
        weights = (w * active_share).view(1, -1, 1, 1)

        cam = F.relu((weights * acts).sum(dim=1, keepdim=True))
        cam = F.interpolate(cam, size=tuple(image_tensor.shape[-2:]),
                            mode="bilinear", align_corners=False)

    cam = cam[0, 0].cpu().numpy()
    cam = cam - cam.min()
    cam = cam / (cam.max() + 1e-8)
    prob = torch.sigmoid(logit).item()
    return prob, cam


def _jet(x):
    """matplotlib's 'jet' colour map, reproduced with numpy (x in 0..1)."""
    r = np.interp(x, [0, 0.35, 0.66, 0.89, 1], [0, 0, 1, 1, 0.5])
    g = np.interp(x, [0, 0.125, 0.375, 0.64, 0.91, 1], [0, 0, 1, 1, 0, 0])
    b = np.interp(x, [0, 0.11, 0.34, 0.65, 1], [0.5, 1, 1, 0, 0])
    return np.stack([r, g, b], axis=-1)


def overlay_heatmap(original_image, cam, alpha=0.4):
    """
    Same look as the notebook: X-ray with a 'jet' heatmap at alpha 0.4.
    original_image : PIL image (the uploaded X-ray)
    cam            : (224, 224) array in 0..1 from grad_cam()
    returns        : PIL RGB image, 224 x 224
    """
    base = original_image.convert("L").resize(cam.shape[::-1]).convert("RGB")
    base = np.asarray(base, dtype=np.float32) / 255.0
    out = (1 - alpha) * base + alpha * _jet(cam)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def image_to_base64_png(pil_image):
    """For returning the heatmap from the API as a string the app can show."""
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")