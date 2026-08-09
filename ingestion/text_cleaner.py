import re
import unicodedata


class TextCleaner:
    """
    Cleans extracted document text while preserving
    semantic structure required for RAG.
    """

    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Normalize Unicode characters while preserving
        meaningful text.
        """

        return unicodedata.normalize(
            "NFKC",
            text
        )

    @staticmethod
    def normalize_line_endings(text: str) -> str:
        """
        Convert Windows/old-style line endings to \\n.
        """

        return text.replace(
            "\r\n",
            "\n"
        ).replace(
            "\r",
            "\n"
        )

    @staticmethod
    def remove_excessive_whitespace(text: str) -> str:
        """
        Remove trailing spaces and excessive blank lines.

        Important:
        We preserve single blank lines because they
        represent section boundaries.
        """

        lines = []

        for line in text.split("\n"):

            # Remove trailing/leading whitespace
            cleaned_line = line.strip()

            lines.append(cleaned_line)

        text = "\n".join(lines)

        # Maximum two consecutive newlines
        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text
        )

        return text

    @staticmethod
    def normalize_bullets(text: str) -> str:
        """
        Normalize common bullet characters.

        We preserve bullets because they contain
        semantic structure.
        """

        text = text.replace(
            "•",
            "-"
        )

        text = text.replace(
            "▪",
            "-"
        )

        text = text.replace(
            "●",
            "-"
        )

        return text

    @staticmethod
    def clean(text: str) -> str:
        """
        Apply all cleaning operations.
        """

        if not text:
            return ""

        text = TextCleaner.normalize_unicode(text)

        text = TextCleaner.normalize_line_endings(text)

        text = TextCleaner.normalize_bullets(text)

        text = TextCleaner.remove_excessive_whitespace(text)

        return text.strip()


if __name__ == "__main__":

    sample_text = """
    # NovaTel   Service

    This   is   a   test.


    • First item
    • Second item



    ## Troubleshooting
    """

    print("=" * 60)
    print("TEXT CLEANER TEST")
    print("=" * 60)

    cleaned = TextCleaner.clean(
        sample_text
    )

    print(cleaned)