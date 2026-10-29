"""Chunking and configuration rules. Runs offline with a fake token counter (one token per word)."""
import os
from pathlib import Path

import pytest

from app.ingestion.chunking import chunk_paragraphs, split_sentences
from app.ingestion.config import ConfigError, IngestConfig, MODEL_TOKEN_LIMIT, load_config
from app.ingestion.pipeline import DocResult, chunk_rows
from app.ingestion.sections import Paragraph
from app.ingestion.tokens import MiniLMTokenCounter, WordCounter

COUNTER = WordCounter()


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def sentences(n: int, per: int = 6, tag: str = "s") -> str:
    """n sentences of `per` words each, e.g. 'Ts0a Ts0b ... Ts0f. Ts1a ...'"""
    return " ".join(" ".join([f"{tag}{i}x{j}" if j else f"{tag.upper()}{i}x{j}" for j in range(per)]) + "." for i in range(n))


def para(text: str, page: int = 1, title: str | None = "T", kind: str = "body") -> Paragraph:
    return Paragraph(text=text, page=page, section_title=title, section_type=kind)


def chunk(paragraphs, target=40, maximum=50, overlap=8):
    return chunk_paragraphs(paragraphs, COUNTER, target, maximum, overlap)


# ---------------------------------------------------------------- sentence splitting

def test_sentence_splitter_keeps_abbreviations_and_initials_together():
    text = "Smith et al. found 5.2 points. J. Doe agreed (e.g. in 2020). Next one follows! Is it? Yes."
    assert split_sentences(text) == [
        "Smith et al. found 5.2 points.", "J. Doe agreed (e.g. in 2020).", "Next one follows!", "Is it?", "Yes."]


def test_sentence_splitter_handles_text_without_punctuation():
    assert split_sentences("no punctuation here at all") == ["no punctuation here at all"]


# ---------------------------------------------------------------- chunk size and boundaries

def test_no_chunk_exceeds_the_maximum_and_none_is_empty():
    paragraphs = [para(sentences(7, 9, f"p{i}")) for i in range(30)]
    chunks = chunk(paragraphs)
    assert chunks
    assert all(c.text.strip() and 0 < c.token_count <= 50 for c in chunks)


def test_whole_paragraphs_are_packed_and_chunks_start_on_paragraph_boundaries():
    paragraphs = [para(sentences(3, 5, f"q{i}")) for i in range(6)]  # 15 words each, target 40
    chunks = chunk(paragraphs, target=40, maximum=50, overlap=1)
    assert chunks[0].text == paragraphs[0].text + "\n\n" + paragraphs[1].text
    assert chunks[1].text.startswith(paragraphs[2].text)


def test_a_long_paragraph_is_split_only_at_sentence_boundaries():
    chunks = chunk([para(sentences(12, 12))], target=40, maximum=50, overlap=8)
    assert len(chunks) > 2
    for c in chunks:
        assert c.text.endswith(".")
        assert c.text[0].isupper()


def test_overlap_is_made_of_whole_trailing_sentences():
    chunks = chunk([para(sentences(12, 6))], target=30, maximum=40, overlap=8)  # 6-word sentences: one fits the overlap
    for previous, following in zip(chunks, chunks[1:]):
        last_sentence = split_sentences(previous.text)[-1]
        assert following.text.startswith(last_sentence)
        assert last_sentence.count(" ") + 1 <= 8


def test_overlap_never_repeats_a_whole_chunk():
    chunks = chunk([para(sentences(4, 6))], target=10, maximum=12, overlap=30)
    assert len(chunks) > 1
    assert len({c.text for c in chunks}) == len(chunks)


def test_a_sentence_longer_than_the_maximum_is_the_only_thing_cut_mid_sentence():
    long_sentence = words(200) + "."
    chunks = chunk([para(long_sentence)], target=40, maximum=50, overlap=8)
    assert all(c.token_count <= 50 for c in chunks)
    rejoined = " ".join(c.text for c in chunks).split()
    assert rejoined[0] == "w0" and rejoined[-1] == "w199."
    assert len(rejoined) == 200  # nothing lost, nothing repeated


def test_page_ranges_follow_the_paragraphs():
    paragraphs = [para(sentences(2, 10, "a"), page=1), para(sentences(2, 10, "b"), page=2), para(sentences(2, 10, "c"), page=3)]
    chunks = chunk(paragraphs, target=60, maximum=70, overlap=5)
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 3)
    chunks = chunk(paragraphs, target=20, maximum=25, overlap=1)
    assert [(c.page_start, c.page_end) for c in chunks] == [(1, 1), (2, 2), (3, 3)]


def test_chunks_never_mix_sections_or_section_types():
    paragraphs = [para(sentences(2, 5, "a"), title="One"), para(sentences(2, 5, "b"), title="Two"),
                  para(sentences(2, 5, "c"), title="Two", kind="references")]
    chunks = chunk(paragraphs, target=100, maximum=120, overlap=5)
    assert [(c.section_title, c.section_type) for c in chunks] == [("One", "body"), ("Two", "body"), ("Two", "references")]


def test_chunking_is_deterministic_and_ordinals_are_continuous():
    paragraphs = [para(sentences(5, 8, f"r{i}"), title=f"S{i % 3}") for i in range(12)]
    first, second = chunk(paragraphs), chunk(paragraphs)
    assert first == second
    assert [c.ordinal for c in first] == list(range(1, len(first) + 1))


def test_chunk_rows_have_stable_ids_and_hashes():
    paragraphs = [para(sentences(5, 8, f"r{i}")) for i in range(6)]
    chunks = chunk(paragraphs)
    result = DocResult(paper_id="demo-paper", status="ingested", chunks=chunks, injection_flags=[False] * len(chunks))
    rows_a, rows_b = chunk_rows("demo-paper", result), chunk_rows("demo-paper", result)
    assert rows_a == rows_b
    assert rows_a[0]["chunk_id"] == "demo-paper-c0001" and rows_a[1]["chunk_id"] == "demo-paper-c0002"
    assert all(len(r["text_sha256"]) == 64 for r in rows_a)


def test_empty_input_gives_no_chunks():
    assert chunk([]) == []


# ---------------------------------------------------------------- configuration

def test_default_configuration_is_valid_and_within_the_model_limit():
    config = IngestConfig()
    assert (config.chunk_target, config.chunk_max, config.chunk_overlap) == (220, 250, 40)
    assert config.validate() == [] and config.chunk_max <= MODEL_TOKEN_LIMIT


@pytest.mark.parametrize("changes,message", [
    ({"chunk_overlap": 220}, "OVERLAP"),
    ({"chunk_overlap": 300}, "OVERLAP"),
    ({"chunk_target": 260, "chunk_max": 250}, "TARGET"),
    ({"chunk_target": 0}, "positive"),
    ({"chunk_overlap": -1}, "positive"),
    ({"needs_ocr_ratio": 0}, "needs_ocr_ratio"),
    ({"chunk_max": 300}, "256"),
])
def test_invalid_configuration_is_rejected(changes, message):
    with pytest.raises(ConfigError, match=message):
        IngestConfig(**changes).validate()


def test_a_maximum_above_the_model_limit_needs_an_explicit_flag_and_warns_loudly():
    config = IngestConfig(chunk_max=300, allow_over_limit=True)
    warnings = config.validate()
    assert warnings and "256" in warnings[0] and warnings[0].startswith("WARNING")


def test_environment_variables_and_overrides(monkeypatch):
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "100")
    monkeypatch.setenv("CHUNK_MAX_TOKENS", "120")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "10")
    config = load_config()
    assert (config.chunk_target, config.chunk_max, config.chunk_overlap) == (100, 120, 10)
    assert load_config(chunk_overlap=20).chunk_overlap == 20
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "abc")
    with pytest.raises(ConfigError):
        load_config()


def test_changing_any_parameter_changes_the_chunking_version():
    base = IngestConfig().version()
    assert "all-MiniLM-L6-v2@1110a243" in base
    assert IngestConfig(chunk_target=200).version() != base
    assert IngestConfig(chunk_overlap=30).version() != base
    assert IngestConfig(low_text_min_chars=80).version() != base
    assert IngestConfig().version() == base


# ---------------------------------------------------------------- the real tokenizer (optional)

REAL_TOKENIZER = IngestConfig().tokenizer_path


@pytest.mark.skipif(not REAL_TOKENIZER.is_file(), reason="tokenizer.json is not downloaded (see docs/INGESTION.md)")
def test_real_tokenizer_counts_special_tokens_and_keeps_chunks_under_the_limit():
    counter = MiniLMTokenCounter(REAL_TOKENIZER)
    assert counter.count("") == 2  # [CLS] and [SEP]
    assert counter.count("hello world") == 4
    text = " ".join(f"Alcohol use disorder treatment outcome number {i} was measured carefully." for i in range(200))
    chunks = chunk_paragraphs([para(text)], counter, 220, 250, 40)
    assert len(chunks) > 3
    assert all(c.token_count <= 250 for c in chunks)
    assert all(counter.count(c.text) == c.token_count for c in chunks)
