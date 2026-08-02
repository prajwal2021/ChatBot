from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(__file__)

AGENTS: dict[str, dict] = {
    "ttu-online": {
        "collection": "ttu_kb",
        "display_name": "TTU Online",
        "description": "Texas Tech University Online programs, admissions, and courses.",
        "kb_folder": os.path.join(BASE_DIR, "kb", "ttu_online"),
        "kb_url": os.getenv("KB_URL_TTU_ONLINE") or os.getenv("KB_URL", ""),
        "routing_terms": [
            r"\bttu online(?:\+)?\b",
            r"\btexas tech (?:university )?online(?:\+)?\b",
            r"\b(?:undergraduate|graduate|bachelor'?s?|master'?s?) (?:online )?degree",
        ],
        "scope_terms": [
            r"\bttu\b", r"\btexas tech\b", r"\bonline\+?\b", r"\bdegree\b",
            r"\b(?:ph\.?d\.?|doctoral|doctorate)\b",
            r"\bprograms?\b", r"\badmission\b", r"\bapplication\b", r"\btuition\b",
            r"\bpayment plan\b", r"\bebill\b", r"\braiderlink\b", r"\bfinancial aid\b",
            r"\btransfer credits?\b", r"\bregister\b", r"\bregistration\b",
            r"\bcourses?\b", r"\bstudent advocate\b", r"\bcareer certificates?\b",
        ],
        "contact": {
            "phone": "1-844-691-0494",
            "email": "online@ttu.edu",
            "url": "https://www.depts.ttu.edu/online/",
        },
        "guardrails": (
            "You are an assistant specifically for Texas Tech University Online (TTU Online) programs. "
            "Only answer questions related to TTU Online. "
            "Use the full conversation history to resolve follow-up references before deciding scope. "
            "Only if the topic is genuinely unrelated to TTU Online and cannot be understood from the "
            "conversation history: if the question is about K-12, competitor universities, general academic advice unrelated to TTU, "
            "medical, legal, or financial advice — politely say that is outside your scope. For unrelated non-TTU "
            "topics, suggest an appropriate general source rather than TTU Online support. Never call a reference "
            "to an earlier assistant response out of scope. "
            "When relevant, use this TTU Online+ contact information: phone 1-844-691-0494, "
            "email online@ttu.edu, programs https://www.depts.ttu.edu/online/programs/, and GoOnline.ttu.edu."
        ),
    },
    "k12": {
        "collection": "k12",
        "display_name": "K-12",
        "description": "K-12 education programs and resources at Texas Tech.",
        "kb_folder": os.path.join(BASE_DIR, "kb", "k12"),
        "kb_url": os.getenv("KB_URL_K12", ""),
        "routing_terms": [
            r"\bttu k-?12\b",
            r"\btexas tech (?:university )?k-?12\b",
            r"\b(?:elementary|middle|high) school (?:student|program|course|enrollment)\b",
            r"\b(?:sixth|6th|seventh|7th|eighth|8th) grader\b",
        ],
        "scope_terms": [
            r"\bttu\b", r"\btexas tech\b", r"\bk-?12\b", r"\bparent portal\b",
            r"\bfocus portal\b", r"\bcounselor portal\b", r"\bstudents?\b",
            r"\bcourses?\b", r"\bcredit by exam\b", r"\bcbe\b", r"\btuition\b",
            r"\bfees?\b", r"\bdiploma\b", r"\btranscript\b", r"\bproctorio\b",
            r"\bexams?\b", r"\bwebcam\b", r"\bmicrophone\b", r"\btechnical support\b",
            r"\bteacher\b", r"\bgrades?\b", r"\benroll(?:ment)?\b", r"\bprogram\b",
            r"\bsupport (?:number|phone|email)\b",
        ],
        "contact": {
            "phone": "1-800-692-6877",
            "email": "ttuk12@ttu.edu",
            "url": "https://www.depts.ttu.edu/k12/",
        },
        "guardrails": (
            "You are an assistant specifically for the Texas Tech University K-12 program (TTU K-12). "
            "Only answer questions related to TTU K-12. "
            "Use the full conversation history to resolve follow-up references before deciding scope. "
            "Only if the topic is genuinely unrelated to TTU K-12 and cannot be understood from the conversation "
            "history, politely say that is outside your scope. For unrelated non-TTU topics, suggest an appropriate "
            "general source rather than the TTU K-12 support team. "
            "Never call a reference to an earlier assistant response out of scope. "
            "When relevant, use this TTU K-12 contact information: phone 1-800-692-6877 and email ttuk12@ttu.edu."
        ),
    },
}
