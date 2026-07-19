import yaml
import os

_DEFAULT_CONFIG = os.getenv("SOURCES_CONFIG", "config/sources.yaml")

class SourceRegistry:
    def __init__(self, config_path: str = _DEFAULT_CONFIG):
        self.config_path = config_path
        self.sources = self._load()

    def _load(self):
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)
        return config.get("sources", [])

    def get_all_sources(self):
        return self.sources

    def get_source_by_name(self, name: str):
        for source in self.sources:
            if source["name"] == name:
                return source
        return None

    def register_source(self, source: dict):
        """Append a new source to sources.yaml if not already registered."""
        name = source["name"]
        if self.get_source_by_name(name):
            return  # already registered
        entry = {
            "name": name,
            "type": source.get("type", "api"),
            "format": source.get("format", "unknown"),
            "base_url": source.get("base_url"),
            "text_field": None,
            "rate_limit": None,
            "id_field": None,
            "search_query": None,
        }
        self.sources.append(entry)
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)
        config.setdefault("sources", []).append(entry)
        with open(self.config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)