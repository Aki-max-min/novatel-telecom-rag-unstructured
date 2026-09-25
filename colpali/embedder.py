import torch

from transformers import ColPaliForRetrieval, ColPaliProcessor


MODEL_NAME = "vidore/colpali-v1.3-hf"


class ColPaliEmbedder:

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Loading ColPali on: {self.device}")

        self.processor = ColPaliProcessor.from_pretrained(
            MODEL_NAME
        )

        self.model = ColPaliForRetrieval.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float16
        )

        self.model = self.model.to(self.device)
        self.model.eval()

        print("ColPali loaded successfully.")

    def embed_image(self, image):
        """
        Generate ColPali representation for a document page.
        """

        inputs = self.processor(
            images=[image],
            return_tensors="pt"
        )

        inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
        }

        with torch.no_grad():
            outputs = self.model(**inputs)

        return outputs.embeddings

    def embed_query(self, query):
        """
        Generate ColPali representation for a text query.
        """

        inputs = self.processor(
            text=[query],
            return_tensors="pt"
        )

        inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
        }

        with torch.no_grad():
            outputs = self.model(**inputs)

        return outputs.embeddings