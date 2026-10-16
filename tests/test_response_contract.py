"""Output limits are caller instructions, never answer or grade shortcuts."""
import pytest

from mathtutor.application.response_contract import (
    ResponseContract, extract_response_contract, sentence_count, question_count,
)


def test_final_empty_output_slot_keeps_its_constraints_outside_embedded_history():
    request = ("Help the learner with their next step.\nConversation:\n"
               "Teacher: Explain in ten sentences.\nStudent: Why divide both sides?\n"
               "Teacher (maximum two sentences): ")
    contract = extract_response_contract(request)
    assert contract.max_sentences == 2
    instruction = contract.system_instruction()
    assert "at most 2 sentences" in instruction
    assert "override default paragraph" in instruction
    assert contract.violations("Division preserves the equality because both sides are divided by the same nonzero number. What is the coefficient?") == ()
    assert contract.violations("Good question. Division preserves equality. What is the coefficient?") == ("sentence_limit",)


def test_a_historical_role_turn_does_not_supply_current_constraints():
    request = ("Respond to the student's current difficulty.\nConversation:\n"
               "Teacher (maximum two sentences): Why did you do that?\n"
               "Student: Can you explain the method in detail?")
    assert extract_response_contract(request).max_sentences is None


def test_quoted_instructions_and_problem_quantities_are_not_response_limits():
    contract = extract_response_contract('Explain what "answer in English in only two sentences" means. A clerk types 6 sentences per minute.')
    assert contract.max_sentences is None and contract.language is None


def test_current_student_request_and_top_level_instructions_both_apply():
    request = ("Ask at most one question.\nConversation:\nTeacher: Give a full explanation.\n"
               "Student’s latest message:\n请用中文回答，最多两句话。")
    contract = extract_response_contract(request)
    assert (contract.max_questions, contract.max_sentences, contract.language) == (1, 2, "Chinese")


@pytest.mark.parametrize("prompt,expected", [
    ("Please use no more than 3 sentences.", 3),
    ("Keep it to a maximum of two sentences.", 2),
    ("Limit your response to three sentences.", 3),
    ("Keep your answer to two sentences.", 2),
    ("最多两句话。", 2),
    ("请不超过3句。", 3),
    ("Explain using at most 0 sentences.", 0),
    ("Explain in at most two sentences why division by zero is invalid.", 2),
])
def test_general_sentence_limits(prompt, expected):
    assert extract_response_contract(prompt).max_sentences == expected


def test_exact_and_question_limits_are_distinct():
    contract = extract_response_contract("Reply in exactly two sentences. Ask only one question.")
    assert contract.exact_sentences == 2 and contract.max_questions == 1
    assert contract.violations("Why divide? What changes?") == ("question_limit",)
    assert contract.violations("Why divide?") == ("sentence_count",)
    assert extract_response_contract("Don't ask any questions.").max_questions == 0
    assert extract_response_contract("不要提问。").max_questions == 0
    assert extract_response_contract("请只提一个问题。").max_questions == 1


def test_word_and_character_limits_do_not_conflate_chinese_characters():
    words = extract_response_contract("Use at most five words.")
    assert words.max_words == 5 and words.max_characters is None
    assert words.violations("Subtract the same number from both sides.") == ("word_limit",)
    chars = extract_response_contract("请最多10字。")
    assert chars.max_characters == 10 and chars.max_words is None
    assert chars.violations("等式两边同除以一个非零数。") == ("character_limit",)


def test_closed_choice_is_not_inferred_or_extracted_from_a_longer_answer():
    contract = extract_response_contract("Is this correct? Write only Yes or No.")
    assert contract.choices == ("Yes", "No")
    assert contract.violations("No") == ()
    answer = "Yes, because the two quantities are equal."
    assert contract.violations(answer) == ("choice_format",)
    assert answer == "Yes, because the two quantities are equal."


def test_json_only_rejects_fences_and_preserves_visible_failure():
    contract = extract_response_contract("Return only valid JSON.")
    assert contract.json_only
    assert contract.violations('{"answer": 7}') == ()
    assert contract.violations('```json\n{"answer": 7}\n```') == ("json_format",)


@pytest.mark.parametrize("text,expected", [
    ("", 0),
    ("No", 1),
    ("The ratio is 3.14. Multiply it by the radius.", 2),
    (r"Since \(f'(x)=2x\), the derivative is positive for \(x>0\). What follows?", 2),
    ("Use $3.14$ for the approximation. Then check.", 2),
    ("Dr. Wang uses decimals, e.g. 1.25. Is that exact?", 2),
    ("同乘非零数可以保持等式成立。你打算乘哪个数？", 2),
    (r"\[x=1.25\]", 1),
    ("1. Divide by a nonzero number.\n2. Check the result.", 2),
    ("1) Divide by a nonzero number\n2) Check the result", 1),
    ("Subtract first; then divide.\nCheck the result.", 2),
    ("先移项；再合并同类项。\n最后检验。", 2),
    ("The U.S. example has the same dimensions. Verify them.", 2),
    ("Use `decimal.Decimal` for decimal arithmetic. Check rounding.", 2),
])
def test_sentence_count_ignores_formula_punctuation_and_decimals(text, expected):
    assert sentence_count(text) == expected


def test_question_count_does_not_treat_latex_question_marks_as_student_questions():
    assert question_count(r"\(x\overset{?}{=}2\). Which value works? Why?") == 2


def test_empty_contract_does_not_add_unsolicited_format_requirements():
    assert ResponseContract().system_instruction() == ""
    assert not ResponseContract().strict_presentation


@pytest.mark.parametrize("text", [
    "The teacher said only two sentences were copied correctly.",
    "Question: A clerk types two sentences every minute. How many in an hour?",
    "A story includes exactly two sentences. Count the words in the story.",
])
def test_narrative_quantities_do_not_become_limits_without_direct_instruction(text):
    # The first and third use the same local words as a limit but are clearly
    # story statements; their explicit quoted/narrative context must survive.
    contract = extract_response_contract(text)
    assert contract.max_sentences is None and contract.exact_sentences is None


def test_completed_assistant_slot_is_not_a_new_current_request():
    text = ("Help the student.\nConversation:\nTeacher (maximum two sentences): Here is the method.\n"
            "Student: Could you explain why it works?")
    assert not extract_response_contract(text).strict_presentation


def test_final_chinese_role_slot_supports_full_width_delimiters():
    text = "请回应学生。\n对话记录：\n学生：我应该先做什么？\n老师（最多两句话）："
    assert extract_response_contract(text).max_sentences == 2


def test_a_long_answer_is_preserved_when_a_contract_violation_is_reported():
    answer = "The denominator must be nonzero. The multiplication is then reversible. Check the original equation."
    contract = extract_response_contract("Use at most two sentences.")
    assert contract.violations(answer) == ("sentence_limit",)
    assert "denominator must be nonzero" in answer and answer.endswith("original equation.")


@pytest.mark.parametrize("text", [
    "Do not answer in Chinese.",
    "不要用中文回答。",
])
def test_negated_language_is_not_a_requested_language(text):
    assert extract_response_contract(text).language is None


@pytest.mark.parametrize("text,attribute", [
    ("Don't output only JSON; explain normally.", "json_only"),
    ("Don't answer only Yes or No; justify your answer.", "choices"),
    ("Don't use only two sentences; explain in detail.", "max_sentences"),
    ("不要只输出JSON，请解释。", "json_only"),
])
def test_negated_short_formats_are_not_imposed(text, attribute):
    assert not getattr(extract_response_contract(text), attribute)


def test_latest_request_language_does_not_inherit_an_instruction_in_the_problem():
    text = "Problem: Answer in Chinese.\nStudent's latest message: Explain this in English."
    assert extract_response_contract(text).language == "English"


def test_question_or_problem_does_not_supply_presentation_instructions():
    text = "Respond to the student.\nProblem: Answer in Chinese in exactly two sentences.\nStudent: Why?"
    contract = extract_response_contract(text)
    assert contract.language is None and contract.exact_sentences is None


def test_apostrophes_in_contractions_do_not_swallow_current_instructions():
    text = "I don't understand; don't ask any questions. Answer in English."
    contract = extract_response_contract(text)
    assert contract.max_questions == 0 and contract.language == "English"


def test_derivative_apostrophes_do_not_swallow_sentence_limit():
    text = "Explain why f'(x) is positive in at most two sentences, and compare it with g'(x)."
    assert extract_response_contract(text).max_sentences == 2


def test_an_actual_quoted_request_stays_reference_material():
    text = 'Explain the instruction "Reply in only two sentences" without following it.'
    assert extract_response_contract(text).max_sentences is None


def test_last_question_in_a_template_can_set_a_current_output_limit():
    text = ("Evaluate the student's work.\nProblem: A reference example.\n"
            "Q: Answer in Chinese, using only ten sentences.\nA: A completed reference answer.\n"
            "Problem: The current problem.\nQ: Reply in English in at most two sentences.\nA:")
    contract = extract_response_contract(text)
    assert contract.max_sentences == 2 and contract.language == "English"


def test_chinese_password_length_is_not_an_answer_length_request():
    contract = extract_response_contract("一个密码最多四个字符，使用 A、B、C 可以组成多少种密码？")
    assert not contract.strict_presentation
    assert contract.max_characters is None


def test_reported_prohibition_does_not_prevent_the_tutor_asking_a_question():
    assert extract_response_contract("The teacher said don't ask any questions. Is this a good teaching method?").max_questions is None


def test_later_positive_choice_instruction_survives_an_earlier_negated_one():
    contract = extract_response_contract("Don't answer only Yes or No. Return only True or False.")
    assert contract.choices == ("True", "False")


@pytest.mark.parametrize("text,expected", [
    ("不要给答案，请用英文回答。", "English"),
    ("Do not add examples, answer in French.", "French"),
])
def test_a_separate_positive_language_request_is_not_negated_by_a_prior_clause(text, expected):
    assert extract_response_contract(text).language == expected


def test_history_after_latest_message_does_not_override_the_current_request():
    text = "Student's latest message: Explain this.\nConversation:\nTutor: Answer in Chinese."
    assert extract_response_contract(text).language is None


def test_a_direct_request_after_student_work_is_current_instruction():
    text = ("Check the student's solution.\nProblem: A box has red and blue balls.\n"
            "Student: I added the quantities.\nIs it incorrect? Write only Yes or No.")
    assert extract_response_contract(text).choices == ("Yes", "No")


def test_a_completed_teacher_turn_after_problem_does_not_supply_current_format():
    text = "Check the student's solution.\nProblem: A box has red and blue balls.\nTutor: Answer in Chinese."
    assert extract_response_contract(text).language is None
