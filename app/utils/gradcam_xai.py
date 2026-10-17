"""
Grad-CAM for the DenseNet-121 pneumonia model (single logit output).

Same file works in:
  1. the Kaggle notebook (paste at the end, after the test section)
  2. the FastAPI backend (e.g. app/utils/gradcam.py)

No extra libraries: only torch, numpy, PIL.
"""
import base64
import io

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


def grad_cam(model, image_tensor):
    """
    model        : your trained DenseNet-121 (already loaded, in eval mode)
    image_tensor : shape (1, 3, 224, 224), preprocessed exactly like val/test
    returns      : (probability_of_pneumonia, cam)  cam is (224, 224) in 0..1
    """
    model.eval()
    model.zero_grad()

    # Re-run the DenseNet forward by hand so the last feature map is kept.
    # torchvision's forward does: features -> relu -> avgpool -> classifier
    with torch.enable_grad():          # needed even if the caller used no_grad
        feats = model.features(image_tensor)
        acts = F.relu(feats)           # NOT inplace, so gradients are safe
        acts.retain_grad()
        pooled = F.adaptive_avg_pool2d(acts, (1, 1)).flatten(1)
        logit = model.classifier(pooled)   # shape (1, 1)
        logit.squeeze().backward()         # gradient of the pneumonia logit

    weights = acts.grad.mean(dim=(2, 3), keepdim=True)        # importance per channel
    cam = F.relu((weights * acts).sum(dim=1, keepdim=True))   # (1, 1, 7, 7)
    cam = F.interpolate(cam, size=image_tensor.shape[-2:],
                        mode="bilinear", align_corners=False)
    cam = cam.squeeze().detach().cpu().numpy()
    cam = (cam - cam.min()) / (cam.max() - cam.min() + 1e-8)

    prob = torch.sigmoid(logit).item()
    return prob, cam


def overlay_heatmap(original_image, cam, alpha=0.45):
    """
    original_image : PIL image (the uploaded X-ray)
    cam            : (H, W) array in 0..1 from grad_cam()
    returns        : PIL RGB image, X-ray with red/yellow heatmap on top
    """
    base = original_image.convert("L").resize(cam.shape[::-1]).convert("RGB")
    base = np.asarray(base, dtype=np.float32) / 255.0

    # simple blue -> yellow -> red ramp, no matplotlib/cv2 needed
    r = np.clip(2 * cam, 0, 1)
    g = np.clip(2 * cam, 0, 1) * np.clip(2 - 2 * cam, 0, 1)
    b = np.clip(1 - 2 * cam, 0, 1) * 0.5
    heat = np.stack([r, g, b], axis=-1)

    # only tint the regions the model actually used (hides the blue background)
    mask = (cam >= 0.2)[..., None] * alpha
    out = base * (1 - mask) + heat * mask
    return Image.fromarray((out * 255).astype(np.uint8))


def image_to_base64_png(pil_image):
    """For returning the heatmap from the API as a string the app can show."""
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------
# NOTEBOOK USAGE (you already have `model`, `transform`, IMAGE_PATH)
# ---------------------------------------------------------------
# from gradcam_xai import grad_cam, overlay_heatmap
# image = Image.open(IMAGE_PATH).convert("L")
# x = transform(image).unsqueeze(0).to(device)
# prob, cam = grad_cam(model, x)
# overlay_heatmap(image, cam).show()      # or display(...) in Kaggle
# print(f"Pneumonia probability: {prob*100:.2f}%")


# ---------------------------------------------------------------
# BACKEND USAGE (inside your existing predict endpoint)
# ---------------------------------------------------------------
# prob, cam = grad_cam(model, image_tensor)          # replaces the plain forward pass
# heatmap_b64 = image_to_base64_png(overlay_heatmap(pil_image, cam))
# return {
#     "prediction": "Pneumonia" if prob >= THRESHOLD else "Normal",
#     "probability": prob,
#     "heatmap_base64": heatmap_b64,
# }