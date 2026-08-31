import os
import zipfile
import requests

DATA_DIR = "data/raw/real_world/scifact"

os.makedirs(DATA_DIR, exist_ok=True)

url = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip"

zip_path = os.path.join(DATA_DIR, "scifact.zip")

print("Downloading SciFact dataset...")

response = requests.get(url)

with open(zip_path, "wb") as f:
    f.write(response.content)

print("Download complete.")

print("Extracting dataset...")

with zipfile.ZipFile(zip_path, "r") as zip_ref:
    zip_ref.extractall(DATA_DIR)

print("Extraction complete.")