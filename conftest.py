import os
import sys
import types
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Return a MagicMock-based stub module and register it in sys.modules."""
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


# tiktoken
if "tiktoken" not in sys.modules:
    _encoder_stub = MagicMock()
    _encoder_stub.encode.side_effect = lambda text: text.split()  # token ≈ word
    _tiktoken = _stub_module("tiktoken")
    _tiktoken.get_encoding = MagicMock(return_value=_encoder_stub)

# torch
if "torch" not in sys.modules:
    _torch = _stub_module("torch")
    _torch.no_grad = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=None),
                                                       __exit__=MagicMock(return_value=False)))
    _torch.softmax = MagicMock(return_value=[MagicMock()])
    _stub_module("torch.nn")
    _stub_module("torch.nn.functional")

# transformers
if "transformers" not in sys.modules:
    _transformers = _stub_module("transformers")
    _transformers.AutoTokenizer = MagicMock()
    _transformers.AutoModelForSequenceClassification = MagicMock()
    _stub_module("transformers.modeling_outputs")

# python-dotenv
if "dotenv" not in sys.modules:
    _dotenv = _stub_module("dotenv")
    _dotenv.load_dotenv = MagicMock()

# fitz (PyMuPDF)
if "fitz" not in sys.modules:
    _fitz = _stub_module("fitz")

    class _FakePage:
        def get_text(self):
            return "fake pdf page text"

    class _FakeDoc:
        def __iter__(self):
            return iter([_FakePage()])

    _fitz.open = MagicMock(return_value=_FakeDoc())

# bs4 (beautifulsoup4)
if "bs4" not in sys.modules:
    _bs4 = _stub_module("bs4")

    class _FakeTag:
        def __init__(self, text=""):
            self._text = text

        def decompose(self):
            pass

        def get_text(self, separator=" ", strip=False):
            return self._text

        def find(self, tag):
            return None

    class _FakeSoup:
        def __init__(self, content, parser):
            self._content = content

        def __call__(self, tags):
            return []

        def find(self, tag):
            return None

        def get_text(self, separator=" ", strip=False):
            # strip HTML tags naively for tests
            import re
            return re.sub(r"<[^>]+>", " ", self._content).strip()

    _bs4.BeautifulSoup = _FakeSoup

# openai and instructor
if "openai" not in sys.modules:
    _openai = _stub_module("openai")
    _openai.OpenAI = MagicMock()

if "instructor" not in sys.modules:
    _instructor = _stub_module("instructor")
    _instructor.patch = MagicMock(return_value=MagicMock())

# spacy + scispacy
# preextractor.py does `import spacy` at module level and calls spacy.load(),
# spacy.blank(), and spacy.util.filter_spans() — stub them all so CI never
# needs to download the large scispaCy NER model packages.
if "spacy" not in sys.modules:
    class _FakeSpan:
        def __init__(self, text="", label_="", start_char=0, end_char=0):
            self.text       = text
            self.label_     = label_
            self.start_char = start_char
            self.end_char   = end_char
            self.start      = 0
            self.end        = 0

    class _FakeDoc:
        def __init__(self, text=""):
            self.text = text
            self.ents  = []
            self.sents = []

        def char_span(self, start, end, label="", alignment_mode="strict"):
            return _FakeSpan(self.text[start:end], label, start, end)

        def __iter__(self):
            return iter([])

    class _FakeNLP:
        def __call__(self, text):
            return _FakeDoc(text)

        def add_pipe(self, name, **kwargs):
            pass

    class _FakeSpacyUtil:
        @staticmethod
        def filter_spans(spans):
            return spans

    _spacy = _stub_module("spacy")
    _spacy.load  = MagicMock(return_value=_FakeNLP())
    _spacy.blank = MagicMock(return_value=_FakeNLP())

    _spacy_util = _stub_module("spacy.util")
    _spacy_util.filter_spans = _FakeSpacyUtil.filter_spans
    _spacy.util = _spacy_util

    _stub_module("spacy.language")
    _stub_module("spacy.tokens")
    _stub_module("scispacy")

# gliner
# gliner_tagger.py does `from gliner import GLiNER` inside a lazy function.
# Stub GLiNER.from_pretrained so model weights are never downloaded in CI.
if "gliner" not in sys.modules:
    class _FakeGLiNER:
        @classmethod
        def from_pretrained(cls, model_id, *args, **kwargs):
            return cls()

        def predict_entities(self, text, labels, threshold=0.5, flat_ner=True):
            return []  # return no entities — safe no-op for tests

    _gliner_mod = _stub_module("gliner")
    _gliner_mod.GLiNER = _FakeGLiNER
