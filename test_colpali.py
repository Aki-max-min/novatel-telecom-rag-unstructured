import torch
from transformers import ColPaliForRetrieval, ColPaliProcessor

MODEL_NAME = "vidore/colpali-v1.3-hf"

print("Loading processor...")
processor = ColPaliProcessor.from_pretrained(MODEL_NAME)

print("Loading model...")
model = ColPaliForRetrieval.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
)

device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

print()
print("====================================")
print("ColPali loaded successfully!")
print("Model:", MODEL_NAME)
print("Device:", device)
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
print("====================================")