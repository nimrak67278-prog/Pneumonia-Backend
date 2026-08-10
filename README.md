# Pneumonia Detection — FastAPI Backend

## 1. Project structure
```
pneumonia_backend/
├── requirements.txt
├── README.md
└── app/
    ├── main.py                  # FastAPI app + /predict endpoint
    ├── model/
    │   └── pneumonia_final_model.keras   <- PUT YOUR DOWNLOADED MODEL FILE HERE
    └── utils/
        ├── model_utils.py       # model loading + prediction logic
        └── explanation.py       # confidence-tiered explanation/recommendation text
```

## 2. Setup

1. Copy your trained model file into `app/model/`:
   - Rename/keep it as `pneumonia_final_model.keras`
   - This is the file you downloaded from Google Drive after training

2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Mac/Linux
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 3. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Then open your browser to:
```
http://127.0.0.1:8000/docs
```

This gives you an interactive Swagger UI — click on `/predict`, click "Try it out",
upload any chest X-ray image, and click Execute. You'll see the full JSON response
with prediction, confidence, explanation, and recommendation.

## 4. Example response

```json
{
  "prediction": "PNEUMONIA",
  "confidence": 94.2,
  "raw_probability": 0.942,
  "risk_level": "high",
  "explanation": "The model detected strong indicators of lung opacity and consolidation patterns that are typically associated with pneumonia.",
  "recommendation": "This is a high-confidence result. Please consult a doctor or pulmonologist as soon as possible for confirmation and treatment.",
  "disclaimer": "This is an AI-assisted screening tool and not a substitute for professional medical diagnosis. Always consult a qualified doctor for confirmation and treatment decisions.",
  "timestamp": "2026-07-07T10:15:32.123456+00:00"
}
```

## 5. Connecting from React Native

Example fetch call from your app:

```javascript
const formData = new FormData();
formData.append('file', {
  uri: imageUri,
  type: 'image/jpeg',
  name: 'xray.jpg',
});

const response = await fetch('http://YOUR_SERVER_IP:8000/predict', {
  method: 'POST',
  body: formData,
  headers: {
    'Content-Type': 'multipart/form-data',
  },
});

const result = await response.json();
```

**Note:** While testing locally, use your laptop's local IP address (not `127.0.0.1`)
so your phone/emulator can reach it over the same WiFi network — e.g. `http://192.168.1.5:8000`.
Find your local IP with `ipconfig` (Windows) or `ifconfig` (Mac/Linux).

## 6. Next steps (not yet included here)
- Firebase Admin SDK integration to save prediction results to Firestore
- Deployment to Render/Railway for a public URL
