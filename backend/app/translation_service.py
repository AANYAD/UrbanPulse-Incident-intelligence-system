"""
Translation service for UrbanPulse using AI4Bharat IndicTrans2.
Implements singleton lazy loading, thread-safe execution, CPU float32 inference,
RAM monitoring, and graceful error handling.
"""

import os
import sys
import time
import ctypes
import logging
import threading
from typing import Dict, Any, Optional

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from transformers.tokenization_utils_base import PreTrainedTokenizerBase
from transformers.modeling_utils import PreTrainedModel

# Transformers 5.2.0 compatibility patch for IndicTransTokenizer & tie_weights
_orig_setattr = PreTrainedTokenizerBase.__setattr__
def _safe_tok_setattr(self, name, value):
    if name in ('unk_token', 'pad_token', 'eos_token', 'bos_token', 'cls_token', 'sep_token', 'mask_token'):
        if '_special_tokens_map' not in self.__dict__:
            self.__dict__['_special_tokens_map'] = {}
    _orig_setattr(self, name, value)
PreTrainedTokenizerBase.__setattr__ = _safe_tok_setattr

_orig_post_init = PreTrainedModel.post_init
def _safe_post_init(self):
    cls = self.__class__
    def _safe_tie(instance, *args, **kwargs):
        if getattr(instance.config, "share_decoder_input_output_embed", False):
            if hasattr(instance, "lm_head") and hasattr(instance, "model") and hasattr(instance.model, "decoder"):
                instance.lm_head.weight = instance.model.decoder.embed_tokens.weight
    cls.tie_weights = _safe_tie
    return _orig_post_init(self)
PreTrainedModel.post_init = _safe_post_init

from app.indic_processor import IndicProcessor

logger = logging.getLogger("urbanpulse.translation")

# Supported source languages mapped to FLORES-200 codes
SUPPORTED_LANGUAGES = {
    "hi": "hin_Deva",
    "hi-in": "hin_Deva",
    "hin_deva": "hin_Deva",
    "ta": "tam_Taml",
    "ta-in": "tam_Taml",
    "tam_taml": "tam_Taml",
    "bn": "ben_Beng",
    "bn-in": "ben_Beng",
    "ben_beng": "ben_Beng",
    "te": "tel_Telu",
    "te-in": "tel_Telu",
    "tel_telu": "tel_Telu",
    "mr": "mar_Deva",
    "mr-in": "mar_Deva",
    "mar_deva": "mar_Deva",
    "en": "eng_Latn",
    "en-in": "eng_Latn",
    "eng_latn": "eng_Latn",
}

TARGET_LANG = "eng_Latn"
MAX_TEXT_LENGTH = 1000
INFERENCE_TIMEOUT_SEC = 30.0

class MemoryInfo:
    @staticmethod
    def get_available_ram_gb() -> float:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong),
                ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong),
                ('sullAvailExtendedVirtual', ctypes.c_ulonglong)
            ]
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(ms)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return round(ms.ullAvailPhys / (1024 ** 3), 2)


class IndicTranslationService:
    _instance: Optional["IndicTranslationService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.model_name = os.getenv("INDIC_MODEL_NAME", "prajdabre/rotary-indictrans2-indic-en-dist-200M")
        self.fallback_model_name = "prajdabre/rotary-indictrans2-indic-en-dist-200M"
        self.device = "cpu"
        self.model = None
        self.tokenizer = None
        self.processor = None
        self._is_loaded = False
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "IndicTranslationService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self):
        if self._is_loaded:
            return

        with self._load_lock:
            if self._is_loaded:
                return

            ram_before = MemoryInfo.get_available_ram_gb()
            logger.info(f"Loading translation model. Available RAM: {ram_before} GB")

            # Check for Hugging Face Token in environment
            hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

            selected_model = self.model_name
            try:
                # Initialize IndicProcessor
                self.processor = IndicProcessor(inference=True)

                # Attempt loading configured model
                logger.info(f"Loading tokenizer from {selected_model}...")
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(
                        selected_model,
                        trust_remote_code=True,
                        token=hf_token
                    )
                except Exception as tok_err:
                    err_str = str(tok_err).lower()
                    if ("401" in err_str or "gated" in err_str or "unauthorized" in err_str) and not hf_token:
                        logger.warning(
                            f"Official model {selected_model} is gated on HF and no HF_TOKEN provided. "
                            f"Falling back to verified co-author repository: {self.fallback_model_name}"
                        )
                        selected_model = self.fallback_model_name
                        self.tokenizer = AutoTokenizer.from_pretrained(
                            selected_model,
                            trust_remote_code=True
                        )
                    else:
                        raise tok_err

                logger.info(f"Loading model weights from {selected_model} in float32 on {self.device}...")
                self.model = AutoModelForSeq2SeqLM.from_pretrained(
                    selected_model,
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=True,
                    local_files_only=True,
                    token=hf_token if selected_model == self.model_name else None
                ).to(self.device)

                self.model.eval()
                self._is_loaded = True
                ram_after = MemoryInfo.get_available_ram_gb()
                logger.info(
                    f"Translation model successfully loaded from {selected_model}. "
                    f"RAM used: {round(ram_before - ram_after, 2)} GB. Remaining RAM: {ram_after} GB."
                )

            except Exception as e:
                logger.error(f"Failed to load translation model: {e}", exc_info=True)
                # Cleanup partially loaded components
                self.model = None
                self.tokenizer = None
                self.processor = None
                self._is_loaded = False
                raise RuntimeError(f"Translation engine initialization failed: {str(e)}")

    def translate(self, text: str, source_lang: str) -> Dict[str, Any]:
        """
        Translates text from the supported source language to English.
        Thread-safe, executes under inference lock.
        """
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            raise ValueError("Input text cannot be empty.")

        if len(cleaned_text) > MAX_TEXT_LENGTH:
            raise ValueError(f"Input text exceeds maximum allowed length of {MAX_TEXT_LENGTH} characters.")

        lang_key = source_lang.strip().lower()
        if lang_key not in SUPPORTED_LANGUAGES:
            supported_keys = ["hi (Hindi)", "ta (Tamil)", "bn (Bengali)", "te (Telugu)", "mr (Marathi)", "en (English)"]
            raise ValueError(f"Unsupported language code '{source_lang}'. Supported: {', '.join(supported_keys)}")

        flores_src = SUPPORTED_LANGUAGES[lang_key]

        # English pass-through: No translation necessary
        if flores_src == TARGET_LANG:
            return {
                "original_text": cleaned_text,
                "translated_text": cleaned_text,
                "source_language": source_lang,
                "source_code": flores_src,
                "target_code": TARGET_LANG,
                "duration_ms": 0.0,
                "was_translated": False
            }

        start_time = time.time()

        # Ensure single-instance thread-safe execution
        with self._inference_lock:
            self._ensure_loaded()

            # Preprocess using IndicProcessor
            preprocessed_batch = self.processor.preprocess_batch(
                [cleaned_text],
                src_lang=flores_src,
                tgt_lang=TARGET_LANG
            )

            # Tokenize
            inputs = self.tokenizer(
                preprocessed_batch,
                truncation=True,
                padding="longest",
                return_tensors="pt"
            ).to(self.device)

            # Generate
            with torch.no_grad():
                generated_tokens = self.model.generate(
                    **inputs,
                    use_cache=False,
                    min_length=0,
                    max_length=256,
                    num_beams=4,
                    num_return_sequences=1
                )

            # Decode tokens
            decoded_outputs = self.tokenizer.batch_decode(
                generated_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True
            )

            # Postprocess back into natural English with entity placeholders restored
            final_translations = self.processor.postprocess_batch(
                decoded_outputs,
                lang=TARGET_LANG
            )

            duration_ms = round((time.time() - start_time) * 1000, 2)
            result_text = final_translations[0].strip()

            return {
                "original_text": cleaned_text,
                "translated_text": result_text,
                "source_language": source_lang,
                "source_code": flores_src,
                "target_code": TARGET_LANG,
                "duration_ms": duration_ms,
                "was_translated": True
            }
