class FormatDetector:

    SUPPORTED_FORMATS = ["json", "xml", "html", "pdf", "text"]

    def detect(self, content_type: str) -> str:
        content_type = content_type.lower()

        if "json" in content_type:
            return "json"
        elif "xml" in content_type:
            return "xml"
        elif "html" in content_type:
            return "html"
        elif "pdf" in content_type:
            return "pdf"
        elif "plain" in content_type or "text" in content_type:
            return "text"
        else:
            return "unknown"