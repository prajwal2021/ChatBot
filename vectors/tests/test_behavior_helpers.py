from __future__ import annotations

import unittest

from ingest import chunk_text_with_sections
from llm import _sanitize_output, get_answer_models
from main import (
    _cross_agent_referral,
    _expand_queries,
    _has_direct_information_signal,
    _has_specific_information_subject,
    _is_context_reference_query,
    _is_greeting_query,
    _is_topics_followup,
    _is_topics_query,
    _latest_history_subject,
    _matches_current_agent_scope,
    _persistent_user_context,
    _resolve_history_reference,
    _resolve_history_list_reference,
)


class ConversationReferenceTests(unittest.TestCase):
    def test_greetings_never_become_retrieval_subjects(self):
        for greeting in ["Hi", "hello!", "Hey there", "Good morning, hi"]:
            with self.subTest(greeting=greeting):
                self.assertTrue(_is_greeting_query(greeting))
        self.assertFalse(_is_greeting_query("Hi, what are the tuition fees?"))

    def test_short_meaningful_subject_is_not_ambiguous(self):
        self.assertTrue(_has_direct_information_signal("phd"))
        self.assertFalse(_has_direct_information_signal("hi"))
        self.assertFalse(_has_direct_information_signal("flag"))

    def test_specific_information_is_not_a_capability_menu(self):
        self.assertTrue(
            _has_specific_information_subject(
                "List online degree program categories with examples"
            )
        )
        self.assertTrue(_has_specific_information_subject("What is the phone and email?"))
        self.assertFalse(_has_specific_information_subject("What kinds of things do you know?"))

    def test_typoed_numbered_followup_uses_displayed_list(self):
        history = [{
            "role": "assistant",
            "content": "1. Programs\n2. Admissions\n3. Deadlines\n4. Tuition\n5. Transfer credits\n6. Registration\n7. Aid\n8. Certificates",
        }]
        resolved = _resolve_history_list_reference(
            "can you talkmore about 4 and 5 also 8",
            history,
        )
        self.assertEqual(
            resolved,
            "Explain these topics: Tuition; Transfer credits; Certificates",
        )

    def test_detail_request_is_contextual(self):
        self.assertTrue(_is_context_reference_query("can you be more detail"))
        self.assertTrue(_is_context_reference_query("can you answer more in detail"))

    def test_detail_followup_preserves_all_previous_sections(self):
        history = [
            {"role": "user", "content": "Explain sections 4, 5, and 8"},
            {
                "role": "assistant",
                "content": (
                    "**Tuition and Fees**\n\nDetails.\n\n"
                    "**Transfer Credits**\n\nDetails.\n\n"
                    "**Industry Certificates**\n\nDetails."
                ),
            },
        ]
        subject = _latest_history_subject(history)
        self.assertIn("Tuition and Fees", subject)
        self.assertIn("Transfer Credits", subject)
        self.assertIn("Industry Certificates", subject)

    def test_natural_capability_questions_are_recognized(self):
        questions = [
            "can you tell me all the topics you can answer about",
            "what are the main topics you can help me with?",
            "what can you help me with",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(_is_topics_query(question))

    def test_list_all_keeps_capability_subject_from_history(self):
        history = [
            {"role": "user", "content": "what can you help me with"},
            {
                "role": "assistant",
                "content": "**Major topics I can help with**\n\n1. Programs\n2. Fees",
            },
        ]
        self.assertTrue(_is_topics_followup("can you give list of all", history))
        self.assertFalse(
            _is_topics_followup(
                "can you give list of all",
                [{"role": "assistant", "content": "Tuition is listed by program."}],
            )
        )

    def test_numbered_markdown_reference_resolves_exact_items(self):
        history = [{
            "role": "assistant",
            "content": (
                "**Major topics**\n\n"
                "1. Programs and enrollment\n"
                "2. **Courses, pacing, and academic policies**\n"
                "3. **Tuition, fees, and payment guidance**"
            ),
        }]
        resolved = _resolve_history_list_reference("Talk about points 2 and 3.", history)
        self.assertIn("Courses, pacing, and academic policies", resolved)
        self.assertIn("Tuition, fees, and payment guidance", resolved)

    def test_all_resolves_previous_markdown_list(self):
        history = [{
            "role": "assistant",
            "content": "**1. First area**\n\n**2. Second area**\n\n**3. Third area**",
        }]
        resolved = _resolve_history_list_reference("all", history)
        self.assertEqual(
            resolved,
            "Explain all of these topics: First area; Second area; Third area",
        )

    def test_pronoun_followup_gets_standalone_subject(self):
        history = [
            {"role": "user", "content": "Explain Credit by Exam at TTU K-12."},
            {"role": "assistant", "content": "**Credit by Exam (CBE)**\n\nStudents may earn credit."},
        ]
        resolved = _resolve_history_reference("How much does this cost and how long do we get?", history)
        self.assertIn("Credit by Exam", resolved)
        self.assertIn("How much does this cost", resolved)

    def test_persistent_user_context_keeps_role_and_location(self):
        history = [
            {"role": "user", "content": "I am a school counselor supporting students."},
            {"role": "assistant", "content": "How can I help?"},
            {"role": "user", "content": "We live in India."},
        ]
        context = _persistent_user_context(history)
        self.assertEqual(len(context), 2)
        self.assertIn("school counselor", context[0])
        self.assertIn("India", context[1])


class RetrievalAndRoutingTests(unittest.TestCase):
    def test_multi_part_question_expands_with_original_subject(self):
        queries = _expand_queries(
            "How much is a CBE, what score passes, how long do I have, and can I retake it?"
        )
        self.assertGreaterEqual(len(queries), 4)
        self.assertTrue(all("CBE" in query for query in queries))

    def test_cross_agent_referral_uses_destination_contact(self):
        response = _cross_agent_referral("ttu-online", "How do I enroll a sixth grader in TTU K-12?")
        self.assertIn("K-12", response)
        self.assertIn("1-800-692-6877", response)
        self.assertNotIn("1-844-691-0494", response)

    def test_current_agent_terms_override_probabilistic_scope_errors(self):
        self.assertTrue(_matches_current_agent_scope("ttu-online", "Walk me through a tuition payment plan"))
        self.assertTrue(_matches_current_agent_scope("k12", "Is this the TTU K-12 support number?"))
        self.assertFalse(_matches_current_agent_scope("k12", "Give me a curry recipe"))

    def test_model_defaults_do_not_include_invalid_identifiers(self):
        self.assertNotIn("gpt-5.6", get_answer_models())
        self.assertNotIn("gpt-5.6-terra", get_answer_models())


class GroundingAndChunkingTests(unittest.TestCase):
    def test_output_sanitizer_removes_source_and_placeholder_link(self):
        answer = "See [the portal](#). This came from document.docx when in the KB."
        clean = _sanitize_output(answer, [], "")
        self.assertNotIn("document.docx", clean.lower())
        self.assertNotIn("when in the kb", clean.lower())
        self.assertNotIn("](#)", clean)

    def test_faq_questions_do_not_share_chunks(self):
        text = (
            "[SECTION] Registration\n"
            "How do I schedule an appointment?\n"
            "Use the appointment scheduler.\n"
            "How do I withdraw?\n"
            "Use the withdrawal form and review financial consequences.\n"
        )
        chunks, _ = chunk_text_with_sections(text)
        appointment = next(chunk for chunk in chunks if "schedule an appointment" in chunk)
        self.assertNotIn("withdrawal form", appointment)

    def test_named_program_sections_do_not_bleed_together(self):
        text = (
            "Online Master of Example One\n"
            "Please submit a résumé and statement.\n"
            "Online Master of Example Two\n"
            "Applicants need a portfolio.\n"
        )
        chunks, _ = chunk_text_with_sections(text)
        first = next(chunk for chunk in chunks if "Example One" in chunk)
        self.assertNotIn("portfolio", first)


if __name__ == "__main__":
    unittest.main()
