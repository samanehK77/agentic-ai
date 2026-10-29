"""The deterministic safety layer: risk screen and output checks. These are heuristics: the tests document what they do
catch AND what they knowingly flag by mistake."""
import pytest

from app.llm.safety import ESCALATION_NOTICE, check_output, screen_question


@pytest.mark.parametrize("question", [
    "What are warning signs of suicide risk in this patient?",
    "Is self-harm common in people with alcohol use disorder?",
    "How is an opioid overdose treated?",
    "Could this patient be at risk of ending his life?",
    "When is a drinking episode a medical emergency?",
])
def test_general_risk_cues_trigger_the_notice_but_not_the_personal_path(question):
    screen = screen_question(question)
    assert screen.triggered and not screen.personal


@pytest.mark.parametrize("question", [
    "I want to die", "I'm going to kill myself tonight", "I took too many pills", "i am suicidal", "I can't go on",
    "I'm going to hurt myself", "I want to end my life",
])
def test_first_person_crisis_statements_are_personal(question):
    screen = screen_question(question)
    assert screen.triggered and screen.personal


@pytest.mark.parametrize("question", [
    "Which medications are used to treat opioid addiction?", "How does motivational interviewing work?",
    "What is behavioral couples therapy?", "Summarise the patient's history.",
])
def test_ordinary_questions_do_not_trigger(question):
    screen = screen_question(question)
    assert not screen.triggered and not screen.personal


def test_the_notice_is_fixed_text_without_phone_numbers_or_countries():
    assert "emergency services" in ESCALATION_NOTICE and "qualified professional" in ESCALATION_NOTICE
    assert not any(ch.isdigit() for ch in ESCALATION_NOTICE)
    for country in ("USA", "United States", "UK", "Iran", "988", "911", "112", "999"):
        assert country not in ESCALATION_NOTICE


@pytest.mark.parametrize("text", [
    "Start naltrexone 50 mg once daily.", "Give 5 mL of the solution", "Take 2 tablets a day", "about 0.5 mg/kg per day",
    "A daily dose of 10 units", "He should take two pills", "She should be prescribed buprenorphine.",
    "I recommend that the patient stops drinking and starts acamprosate", "You should stop taking the medication.",
    "Increase taking it gradually", "The best treatment for P-001 is naltrexone.", "Prescribe him methadone.",
    "The patient should start medication now.",
])
def test_dosing_and_treatment_directives_are_flagged(text):
    assert check_output(text), text


@pytest.mark.parametrize("text", [
    "Studies compare psychosocial approaches such as contingency management.",
    "Heavy drinking days were reduced in the combined treatment groups.",
    "The review included 29 randomised trials with 5,000 participants.",
    "Naltrexone is one option that the guideline discusses.",
])
def test_ordinary_research_statements_are_not_flagged(text):
    assert check_output(text) == []


def test_known_false_positive_a_trial_dose_is_withheld():
    # Documented limitation: the check cannot tell a dose studied in a trial from a dose instruction.
    assert "dosing_instruction" in check_output("Participants in the trial received naltrexone 50 mg.")


def test_flag_codes_are_specific():
    assert check_output("Take 50 mg") == ["dosing_instruction"]
    assert check_output("She should be prescribed it") == ["treatment_directive"]
    assert check_output("Take 50 mg; she should be prescribed it") == ["dosing_instruction", "treatment_directive"]
