"""
Loads the trained EfficientNetB3 pneumonia detection model once at startup,
and provides a function to run predictions on a single image.
Model is downloaded from Google Drive if not already present locally.
"""

import os
import numpy as np
from PIL import Image
import tensorflow as tf
from tensorflow.keras.applications.efficientnet import preprocess_input
import gdown

# Google Drive file ID extracted from your shareable link
DRIVE_FILE_ID = "1mv0lfWajrZyHbG0acNse_uPGbyflnFWr"
MODEL_PATH = "app/model/pneumonia_final_model.keras"
IMG_SIZE = (300, 300)

# Download model from Google Drive if not already present locally
if not os.path.exists(MODEL_PATH):
    print("Model not found locally. Downloading from Google Drive...")
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    gdown.download(
        f"https://drive.google.com/uc?id={DRIVE_FILE_ID}",
        MODEL_PATH,
        quiet=False
    )
    print("Model downloaded successfully.")

# Loaded once when the module is imported (i.e. once at server startup),
# NOT on every request -- loading a Keras model per-request would be very slow.
print("Loading pneumonia detection model...")
model = tf.keras.models.load_model(MODEL_PATH)
print("Model loaded successfully.")


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """Convert raw uploaded image bytes into a model-ready array."""
    from io import BytesIO

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img = img.resize(IMG_SIZE)
    img_array = np.array(img, dtype=np.float32)
    img_array = np.expand_dims(img_array, axis=0)
    img_array = preprocess_input(img_array)
    return img_array


def predict_pneumonia(image_bytes: bytes) -> dict:
    """
    Run inference on a single X-ray image.

    Returns:
        dict with keys: label, confidence (0-100), raw_probability (0-1)
    """
    img_array = preprocess_image(image_bytes)
    prob = float(model.predict(img_array, verbose=0)[0][0])

    label = "PNEUMONIA" if prob >= 0.5 else "NORMAL"
    confidence = prob * 100 if prob >= 0.5 else (1 - prob) * 100

    return {
        "label": label,
        "confidence": round(confidence, 2),
        "raw_probability": round(prob, 4),
    }