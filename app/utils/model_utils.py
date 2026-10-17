"""
app/utils/model_utils.py  (REPLACES the old file)

Loads the retrained DenseNet-121 once at startup and exposes
predict_pneumonia(image_bytes), same name main.py already imports.

Returned dict keeps the old keys (label, confidence 0-100, raw_probability)
and adds heatmap_base64 for the Grad-CAM explanation.
"""
import io
import os

import gdown
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

from app.utils.gradcam import grad_cam, overlay_heatmap, image_to_base64_png

# ---------------------------------------------------------------
# SETTINGS (already matched to your old model_utils.py / explanation.py)
# ---------------------------------------------------------------
# Upload the slim .pth to Google Drive (share: "Anyone with the link"),
# paste its file ID here. Same approach as your old .keras model.
DRIVE_FILE_ID = "/1TtWC_cCMPjl5Y4L9t3F3Lm-2btpnS_Wx/"
MODEL_PATH = "app/model/densenet121_pneumonia.pth"
THRESHOLD = 0.50                 # same as the notebook test results
LABEL_PNEUMONIA = "PNEUMONIA"    # explanation.py compares against these exact strings
LABEL_NORMAL = "NORMAL"

DEVICE = torch.device("cpu")     # Railway has no GPU

# Exactly the notebook's validation/test transform
_transform = transforms.Compose([
    transforms.Grayscale(num_output_channels=3),
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


if not os.path.exists(MODEL_PATH):
    print("Model not found locally. Downloading from Google Drive...")
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    gdown.download(f"https://drive.google.com/uc?id={DRIVE_FILE_ID}", MODEL_PATH, quiet=False)
    print("Model downloaded successfully.")


def _load_model():
    model = models.densenet121(weights=None)
    model.classifier = nn.Linear(model.classifier.in_features, 1)

    state = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)
    if isinstance(state, dict) and "model_state_dict" in state:
        state = state["model_state_dict"]      # full training checkpoint
    model.load_state_dict(state)

    model.to(DEVICE)
    model.eval()
    return model


# Loaded once when the server starts, not on every request
_model = _load_model()


def predict_pneumonia(image_bytes: bytes) -> dict:
    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    x = _transform(image).unsqueeze(0).to(DEVICE)

    # one pass gives both the probability and the Grad-CAM heatmap
    prob, cam = grad_cam(_model, x)

    is_pneumonia = prob >= THRESHOLD
    label = LABEL_PNEUMONIA if is_pneumonia else LABEL_NORMAL
    confidence = (prob if is_pneumonia else 1.0 - prob) * 100   # 0-100, as before

    heatmap_b64 = image_to_base64_png(overlay_heatmap(image, cam))

    return {
        "label": label,
        "confidence": round(confidence, 2),
        "raw_probability": round(prob, 4),
        "heatmap_base64": heatmap_b64,
    }