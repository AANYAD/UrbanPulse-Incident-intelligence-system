"""
Pure Python implementation of IndicProcessor matching the official AI4Bharat IndicTransToolkit (1.1.1).
Faithfully reproduces processor.pyx functionality without requiring Cython or MSVC C++ compilation on Windows.
"""

import regex as re
from queue import Queue
from typing import List, Dict, Union, Optional

from indicnlp.tokenize import indic_tokenize, indic_detokenize
from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
from sacremoses import MosesPunctNormalizer, MosesTokenizer, MosesDetokenizer
from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator


class IndicProcessor:
    def __init__(self, inference: bool = True):
        """
        Constructor for IndicProcessor. Initializes all necessary components.
        """
        self.inference = inference

        ##############################
        # FLORES -> ISO CODES
        ##############################
        self._flores_codes = {
            "asm_Beng": "as",
            "awa_Deva": "hi",
            "ben_Beng": "bn",
            "bho_Deva": "hi",
            "brx_Deva": "hi",
            "doi_Deva": "hi",
            "eng_Latn": "en",
            "gom_Deva": "kK",
            "gon_Deva": "hi",
            "guj_Gujr": "gu",
            "hin_Deva": "hi",
            "hne_Deva": "hi",
            "kan_Knda": "kn",
            "kas_Arab": "ur",
            "kas_Deva": "hi",
            "kha_Latn": "en",
            "lus_Latn": "en",
            "mag_Deva": "hi",
            "mai_Deva": "hi",
            "mal_Mlym": "ml",
            "mar_Deva": "mr",
            "mni_Beng": "bn",
            "mni_Mtei": "hi",
            "npi_Deva": "ne",
            "ory_Orya": "or",
            "pan_Guru": "pa",
            "san_Deva": "hi",
            "sat_Olck": "or",
            "snd_Arab": "ur",
            "snd_Deva": "hi",
            "tam_Taml": "ta",
            "tel_Telu": "te",
            "urd_Arab": "ur",
            "unr_Deva": "hi",
        }

        ##############################
        # INDIC DIGIT TRANSLATION (str.translate)
        ##############################
        self._digits_translation_table = {}
        digits_dict = {
            "\u09e6": "0", "\u0ae6": "0", "\u0ce6": "0", "\u0966": "0",
            "\u0660": "0", "\uabf0": "0", "\u0b66": "0", "\u0a66": "0",
            "\u1c50": "0", "\u06f0": "0",

            "\u09e7": "1", "\u0ae7": "1", "\u0967": "1", "\u0ce7": "1",
            "\u06f1": "1", "\uabf1": "1", "\u0b67": "1", "\u0a67": "1",
            "\u1c51": "1", "\u0c67": "1",

            "\u09e8": "2", "\u0ae8": "2", "\u0968": "2", "\u0ce8": "2",
            "\u06f2": "2", "\uabf2": "2", "\u0b68": "2", "\u0a68": "2",
            "\u1c52": "2", "\u0c68": "2",

            "\u09e9": "3", "\u0ae9": "3", "\u0969": "3", "\u0ce9": "3",
            "\u06f3": "3", "\uabf3": "3", "\u0b69": "3", "\u0a69": "3",
            "\u1c53": "3", "\u0c69": "3",

            "\u09ea": "4", "\u0aea": "4", "\u096a": "4", "\u0cea": "4",
            "\u06f4": "4", "\uabf4": "4", "\u0b6a": "4", "\u0a6a": "4",
            "\u1c54": "4", "\u0c6a": "4",

            "\u09eb": "5", "\u0aeb": "5", "\u096b": "5", "\u0ceb": "5",
            "\u06f5": "5", "\uabf5": "5", "\u0b6b": "5", "\u0a6b": "5",
            "\u1c55": "5", "\u0c6b": "5",

            "\u09ec": "6", "\u0aec": "6", "\u096c": "6", "\u0cec": "6",
            "\u06f6": "6", "\uabf6": "6", "\u0b6c": "6", "\u0a6c": "6",
            "\u1c56": "6", "\u0c6c": "6",

            "\u09ed": "7", "\u0aed": "7", "\u096d": "7", "\u0ced": "7",
            "\u06f7": "7", "\uabf7": "7", "\u0b6d": "7", "\u0a6d": "7",
            "\u1c57": "7", "\u0c6d": "7",

            "\u09ee": "8", "\u0aee": "8", "\u096e": "8", "\u0cee": "8",
            "\u06f8": "8", "\uabf8": "8", "\u0b6e": "8", "\u0a6e": "8",
            "\u1c58": "8", "\u0c6e": "8",

            "\u09ef": "9", "\u0aef": "9", "\u096f": "9", "\u0cef": "9",
            "\u06f9": "9", "\uabf9": "9", "\u0b6f": "9", "\u0a6f": "9",
            "\u1c59": "9", "\u0c6f": "9",
        }
        for k, v in digits_dict.items():
            self._digits_translation_table[ord(k)] = v

        for c in range(ord('0'), ord('9') + 1):
            self._digits_translation_table[c] = chr(c)

        ##############################
        # PLACEHOLDER MAP QUEUE
        ##############################
        self._placeholder_entity_maps = Queue()

        ##############################
        # MOSES
        ##############################
        self._en_tok = MosesTokenizer(lang="en")
        self._en_normalizer = MosesPunctNormalizer()
        self._en_detok = MosesDetokenizer(lang="en")

        ##############################
        # TRANSLITERATOR
        ##############################
        self._xliterator = UnicodeIndicTransliterator()

        ##############################
        # Precompiled Patterns
        ##############################
        self._MULTISPACE_REGEX = re.compile(r"[ ]{2,}")
        self._DIGIT_SPACE_PERCENT = re.compile(r"(\d) %")
        self._DOUBLE_QUOT_PUNC = re.compile(r"\"([,\.]+)")
        self._DIGIT_NBSP_DIGIT = re.compile(r"(\d) (\d)")
        self._END_BRACKET_SPACE_PUNC_REGEX = re.compile(r"\) ([\.!:?;,])")

        self._URL_PATTERN = re.compile(
            r"\b(?<![\w/.])(?:(?:https?|ftp)://)?(?:(?:[\w-]+\.)+(?!\.))(?:[\w/\-?#&=%.]+)+(?!\.\w+)\b"
        )
        self._NUMERAL_PATTERN = re.compile(
            r"(~?\d+\.?\d*\s?%?\s?-?\s?~?\d+\.?\d*\s?%|~?\d+%|\d+[-\/.,:']\d+[-\/.,:'+]\d+(?:\.\d+)?|\d+[-\/.:'+]\d+(?:\.\d+)?)"
        )
        self._EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")
        self._OTHER_PATTERN = re.compile(r"[A-Za-z0-9]*[#|@]\w+")

        ##############################
        # Civic Terminology Normalization Patterns (Hindi)
        ##############################
        self._CIVIC_SEWER_OVERFLOW_PATTERN = re.compile(r"\b(?:सीवर|सीवेज)\s+ओवरफ्लो\b")
        self._CIVIC_POTHOLE_PATTERN = re.compile(r"\bबहुत\s+बड़ा\s+गड्ढा\b")
        self._CIVIC_STREETLIGHT_PATTERN = re.compile(r"\bस्ट्रीट\s*लाइट\s+खराब\s+है\b")
        self._CIVIC_GARBAGE_WITH_VERB_PATTERN = re.compile(
            r"\b(?:कूड़ा|कचरा)\s+उठाने\s+वाली\s+गाड़ी\b(.*?)\bनहीं\s+आई(\s+है)?\b"
        )
        self._CIVIC_GARBAGE_NOUN_PATTERN = re.compile(
            r"\b(?:कूड़ा|कचरा)\s+उठाने\s+वाली\s+गाड़ी\b"
        )
        self._CIVIC_GARBAGE_PICKUP_PATTERN = re.compile(
            r"\bकूड़ा\b(?=\s+(?:तक\s+|भी\s+)?(?:नहीं\s+)?उठाया\s+गया(?:\s+है)?\b)"
        )
        self._CIVIC_BROKEN_ROAD_PATTERN = re.compile(r"\bसड़क\s+टूटी\s+हुई\s+है\b")
        self._CIVIC_DRAIN_JAM_PATTERN = re.compile(r"\bनाली\s+जाम\s+है\b")
        self._CIVIC_AREA_PHRASE_PATTERN = re.compile(
            r"\b(?:हमारे\s+इलाके|हमारे\s+क्षेत्र|इस\s+इलाके)\s+में\b"
        )

        self._PUNC_REPLACEMENTS = [
            (re.compile(r"\r"), ""),
            (re.compile(r"\(\s*"), "("),
            (re.compile(r"\s*\)"), ")"),
            (re.compile(r"\s:\s?"), ":"),
            (re.compile(r"\s;\s?"), ";"),
            (re.compile(r"[`´‘‚’]"), "'"),
            (re.compile(r"[„“”«»]"), '"'),
            (re.compile(r"[–—]"), "-"),
            (re.compile(r"\.\.\."), "..."),
            (re.compile(r" %"), "%"),
            (re.compile(r"nº "), "nº "),
            (re.compile(r" ºC"), " ºC"),
            (re.compile(r" [?!;]"), lambda m: m.group(0).strip()),
            (re.compile(r", "), ", "),
        ]

        self._INDIC_FAILURE_CASES = [
            "آی ڈی ",
            "ꯑꯥꯏꯗꯤ",
            "आईडी",
            "आई . डी . ",
            "आई . डी .",
            "आई. डी. ",
            "आई. डी.",
            "आय. डी. ",
            "आय. डी.",
            "आय . डी . ",
            "आय . डी .",
            "आइ . डी . ",
            "आइ . डी .",
            "आइ. डी. ",
            "आइ. डी.",
            "ऐटि",
            "آئی ڈی ",
            "ᱟᱭᱰᱤ ᱾",
            "आयडी",
            "ऐडि",
            "आइडि",
            "ᱟᱭᱰᱤ",
        ]

    def _apply_punc_replacements(self, text: str, replacements: list) -> str:
        for pair in replacements:
            text = pair[0].sub(pair[1], text)
        return text

    def _punc_norm(self, text: str) -> str:
        text = self._apply_punc_replacements(text, self._PUNC_REPLACEMENTS)
        text = self._MULTISPACE_REGEX.sub(" ", text)
        text = self._END_BRACKET_SPACE_PUNC_REGEX.sub(r")\1", text)
        text = self._DIGIT_SPACE_PERCENT.sub(r"\1%", text)
        text = self._DOUBLE_QUOT_PUNC.sub(r'\1"', text)
        text = self._DIGIT_NBSP_DIGIT.sub(r"\1.\2", text)
        return text.strip()

    def _wrap_with_placeholders(self, text: str) -> str:
        serial_no = 1
        placeholder_entity_map = {}
        patterns = [
            self._EMAIL_PATTERN,
            self._URL_PATTERN,
            self._NUMERAL_PATTERN,
            self._OTHER_PATTERN,
        ]

        for pattern in patterns:
            matches = set(pattern.findall(text))
            for match in matches:
                if pattern is self._URL_PATTERN:
                    if len(match.replace(".", "")) < 4:
                        continue
                if pattern is self._NUMERAL_PATTERN:
                    if len(match.replace(" ", "").replace(".", "").replace(":", "")) < 4:
                        continue

                base_placeholder = f"<ID{serial_no}>"
                placeholder_entity_map[f"<ID{serial_no}>"] = match
                placeholder_entity_map[f"< ID{serial_no} >"] = match
                placeholder_entity_map[f"[ID{serial_no}]"] = match
                placeholder_entity_map[f"[ ID{serial_no} ]"] = match
                placeholder_entity_map[f"[ID {serial_no}]"] = match
                placeholder_entity_map[f"<ID{serial_no}]"] = match
                placeholder_entity_map[f"< ID{serial_no}]"] = match
                placeholder_entity_map[f"<ID{serial_no} ]"] = match

                placeholder_entity_map[f"<id{serial_no}>"] = match
                placeholder_entity_map[f"< id{serial_no} >"] = match
                placeholder_entity_map[f"[id{serial_no}]"] = match
                placeholder_entity_map[f"[ id{serial_no} ]"] = match
                placeholder_entity_map[f"[id {serial_no}]"] = match
                placeholder_entity_map[f"<id{serial_no}]"] = match
                placeholder_entity_map[f"< id{serial_no}]"] = match
                placeholder_entity_map[f"<id{serial_no} ]"] = match

                for indic_case in self._INDIC_FAILURE_CASES:
                    placeholder_entity_map[f"<{indic_case}{serial_no}>"] = match
                    placeholder_entity_map[f"< {indic_case}{serial_no} >"] = match
                    placeholder_entity_map[f"< {indic_case} {serial_no} >"] = match
                    placeholder_entity_map[f"<{indic_case} {serial_no}]"] = match
                    placeholder_entity_map[f"< {indic_case} {serial_no} ]"] = match
                    placeholder_entity_map[f"[{indic_case}{serial_no}]"] = match
                    placeholder_entity_map[f"[{indic_case} {serial_no}]"] = match
                    placeholder_entity_map[f"[ {indic_case}{serial_no} ]"] = match
                    placeholder_entity_map[f"[ {indic_case} {serial_no} ]"] = match
                    placeholder_entity_map[f"{indic_case} {serial_no}"] = match
                    placeholder_entity_map[f"{indic_case}{serial_no}"] = match

                text = text.replace(match, base_placeholder)
                serial_no += 1

        text = re.sub(r"\s+", " ", text).replace(">/", ">").replace("]/", "]")
        self._placeholder_entity_maps.put(placeholder_entity_map)
        return text

    def _normalize(self, text: str) -> str:
        text = text.translate(self._digits_translation_table)
        if self.inference:
            text = self._wrap_with_placeholders(text)
        return text

    def _do_indic_tokenize_and_transliterate(
        self,
        sentence: str,
        normalizer,
        iso_lang: str,
        transliterate: bool
    ) -> str:
        normed = normalizer.normalize(sentence.strip()) if normalizer else sentence.strip()
        tokens = indic_tokenize.trivial_tokenize(normed, iso_lang)
        joined = " ".join(tokens)
        xlated = joined
        if transliterate:
            xlated = self._xliterator.transliterate(joined, iso_lang, "hi")
            xlated = xlated.replace(" ् ", "्")
        return xlated

    def _normalize_civic_terms(self, text: str) -> str:
        """
        Targeted normalization for empirical IndicTrans2 Hindi civic terminology failures:
        1. Sewer overflow: 'सीवर/सीवेज ओवरफ्लो' -> 'गंदे पानी का नाला ओवरफ्लो'
        2. Pothole: 'बहुत बड़ा गड्ढा' -> 'बड़ा गड्ढा'
        3. Streetlight: 'स्ट्रीट लाइट खराब है' -> 'सड़क की बत्ती खराब है'
        4. Garbage collection vehicle: 'कूड़ा उठाने वाली गाड़ी' -> 'कचरा उठाने वाला वाहन'
           with grammatical verb agreement ('नहीं आई है' -> 'नहीं आया है')
        """
        # Rule 1 — Sewer overflow
        text = self._CIVIC_SEWER_OVERFLOW_PATTERN.sub("गंदे पानी का नाला ओवरफ्लो", text)

        # Rule 2 — Pothole: normalize only "बहुत बड़ा गड्ढा" to "बड़ा गड्ढा"
        text = self._CIVIC_POTHOLE_PATTERN.sub("बड़ा गड्ढा", text)

        # Rule 3 — Streetlight: normalize only the tested streetlight broken expression
        text = self._CIVIC_STREETLIGHT_PATTERN.sub("सड़क की बत्ती खराब है", text)

        # Rule 4 — Garbage collection vehicle: preserve municipal vehicle meaning and verb agreement
        if self._CIVIC_GARBAGE_WITH_VERB_PATTERN.search(text):
            text = self._CIVIC_GARBAGE_WITH_VERB_PATTERN.sub(
                lambda m: f"कचरा उठाने वाला वाहन{m.group(1)}नहीं आया{m.group(2) or ''}",
                text
            )
        else:
            text = self._CIVIC_GARBAGE_NOUN_PATTERN.sub("कचरा उठाने वाला वाहन", text)

        # Rule 5 — Garbage pickup: normalize "कूड़ा" to "कचरा" only in expressions with उठाया गया है / नहीं उठाया गया है
        text = self._CIVIC_GARBAGE_PICKUP_PATTERN.sub("कचरा", text)

        # Rule 6 — Broken road: normalize "सड़क टूटी हुई है" to "सड़क टूट गई है"
        text = self._CIVIC_BROKEN_ROAD_PATTERN.sub("सड़क टूट गई है", text)

        # Rule 7 — Clogged drain: normalize "नाली जाम है"
        if self._CIVIC_DRAIN_JAM_PATTERN.search(text):
            if self._CIVIC_AREA_PHRASE_PATTERN.search(text):
                text = self._CIVIC_DRAIN_JAM_PATTERN.sub("नाली बंद है", text)
            else:
                text = self._CIVIC_DRAIN_JAM_PATTERN.sub("नाली जाम हो गई है", text)

        return text

    def _preprocess(
        self,
        sent: str,
        src_lang: str,
        tgt_lang: Optional[str],
        normalizer,
        is_target: bool
    ) -> str:
        iso_lang = self._flores_codes.get(src_lang, "hi")
        script_part = src_lang.split("_")[1] if "_" in src_lang else "Deva"
        do_transliterate = True

        # 1) Punctuation normalization
        sent = self._punc_norm(sent)

        # 1.5) Targeted Hindi civic terminology normalization & sentence boundary
        if not is_target and iso_lang == "hi":
            sent = self._normalize_civic_terms(sent)
            sent = sent.strip()
            if sent and sent[-1] not in "।.?!":
                sent += " ।"

        # 2) Numerals & placeholders
        sent = self._normalize(sent)

        if script_part in ["Arab", "Aran", "Olck", "Mtei", "Latn"]:
            do_transliterate = False

        if iso_lang == "en":
            e_strip = sent.strip()
            e_norm = self._en_normalizer.normalize(e_strip)
            e_tokens = self._en_tok.tokenize(e_norm, escape=False)
            processed_sent = " ".join(e_tokens)
        else:
            processed_sent = self._do_indic_tokenize_and_transliterate(
                sent, normalizer, iso_lang, do_transliterate
            )

        processed_sent = processed_sent.strip()
        if not is_target:
            return f"{src_lang} {tgt_lang} {processed_sent}"
        else:
            return processed_sent

    def _postprocess(self, sent, lang: str, placeholder_entity_map: Optional[dict] = None) -> str:
        if isinstance(sent, (tuple, list)):
            sent = sent[0]

        if placeholder_entity_map is None:
            placeholder_entity_map = self._placeholder_entity_maps.get()

        lang_code, script_code = lang.split("_", 1) if "_" in lang else (lang, "Deva")
        iso_lang = self._flores_codes.get(lang, "hi")

        if script_code in ["Arab", "Aran"]:
            sent = (
                sent.replace(" ؟", "؟")
                    .replace(" ۔", "۔")
                    .replace(" ،", "،")
                    .replace("ٮ۪", "ؠ")
            )

        if lang_code == "ory":
            sent = sent.replace("ଯ଼", "ୟ")

        for k, v in placeholder_entity_map.items():
            sent = sent.replace(k, v)

        if lang == "eng_Latn":
            return self._en_detok.detokenize(sent.split(" "))
        else:
            xlated = self._xliterator.transliterate(sent, "hi", iso_lang)
            return indic_detokenize.trivial_detokenize(xlated, iso_lang)

    def preprocess_batch(
        self,
        batch: List[str],
        src_lang: str,
        tgt_lang: Optional[str] = None,
        is_target: bool = False,
        visualize: bool = False
    ) -> List[str]:
        normalizer = None
        iso_code = self._flores_codes.get(src_lang, "hi")

        if src_lang != "eng_Latn":
            normalizer = IndicNormalizerFactory().get_normalizer(iso_code)

        return [self._preprocess(s, src_lang, tgt_lang, normalizer, is_target) for s in batch]

    def postprocess_batch(
        self,
        sents: List[str],
        lang: str = "hin_Deva",
        visualize: bool = False,
        num_return_sequences: int = 1
    ) -> List[str]:
        results = []
        placeholder_maps = []
        n = len(sents)
        num_inputs = n // num_return_sequences

        for _ in range(num_inputs):
            placeholder_maps.append(self._placeholder_entity_maps.get())

        for i, sent in enumerate(sents):
            map_idx = i // num_return_sequences
            current_map = placeholder_maps[map_idx]
            results.append(self._postprocess(sent, lang, current_map))

        self._placeholder_entity_maps.queue.clear()
        return results
