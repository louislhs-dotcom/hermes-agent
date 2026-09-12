"""Injection pattern definitions for prompt-injection detection.

Each pattern is a (name, compiled_regex) tuple. Patterns are designed to
match common prompt-injection vectors while minimising false positives on
legitimate user messages.
"""

import re
from typing import Optional, List, Tuple

# ---------------------------------------------------------------------------
# Pattern compilation helper
# ---------------------------------------------------------------------------

def _p(pattern: str) -> re.Pattern:
    """Compile a regex with IGNORECASE and UNICODE flags, DOTALL where needed."""
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


# ---------------------------------------------------------------------------
# Injection patterns
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # --- System prompt override attempts ---
    ("system_override", _p(r'ignore\s+(all\s+|the\s+|your\s+)?(previous|prior|above|initial|original)\s+(instructions?|directives?|commands?|rules?|guidelines?)')),
    ("disregard_instructions", _p(r'disregard\s+(all\s+|your\s+|the\s+)?(previous|prior|above|initial)\s+(instructions?|directives?|rules?)')),
    ("forget_instructions", _p(r'forget\s+(everything|all\s+(your\s+)?(previous|prior|initial)\s+(instructions?|rules?|guidelines?))')),
    ("stop_following", _p(r"stop\s+following\s+(your|the)\s+(instructions?|rules?|guidelines?)")),
    ("override_rules", _p(r'override\s+(your|the)\s+(system|base|core|safety|security)\s+(rules?|instructions?|guardrails?|guidelines?)')),

    # --- Role/persona override ---
    ("you_are_now", _p(r'you\s+are\s+now\s+(a\s+|an\s+)?')),
    ("act_as", _p(r'act\s+as\s+(if\s+you\s+are\s+)?(a\s+|an\s+)?(hacker|dan|jailbreak|unrestricted|null|developer|admin)'),
               # Narrower: only trigger for dangerous roles
               ),
    ("act_as_broad", _p(r'act\s+as\s+(if\s+you\s+are\s+|a\s+|an\s+)?(different\s+)?(ai|model|assistant|bot|system)\b')),
    ("from_now_on", _p(r'from\s+now\s+on\s*[,\.]?\s*you\s+are\s+')),
    ("will_now_act", _p(r'you\s+will\s+now\s+(act|behave|respond|operate)\s+(as|like)\s+')),
    ("pretend_to_be", _p(r'pretend\s+(to\s+be|you\s+are)\s+(a\s+|an\s+)?(developer|admin|hacker|unrestricted|null|free|jailbroken|dan)')),
    ("simulate_role", _p(r'simulate\s+(a\s+|an\s+)?(developer|admin|hacker|unrestricted|null)\s+(mode|role|persona)')),
    ("roleplay_override", _p(r'roleplay\s+as\s+(a\s+|an\s+)?(developer|admin|hacker|unrestricted|null|free|jailbroken|dan)')),
    ("no_restrictions", _p(r'(you\s+have\s+)?no\s+(restrictions?|rules?|limits?|guidelines?|guardrails?|boundaries?)')),
    ("remove_safety", _p(r'remove\s+(your\s+|the\s+)?(safety|security|content)\s+(filter|guardrails?|guidelines?|restrictions?|measures?)')),
    ("bypass_safety", _p(r'bypass\s+(your|the)\s+(safety|security|content)\s+(filter|guardrails?|guidelines?|restrictions?)')),
    ("developer_mode", _p(r'(enable|enter|activate|switch\s+to)\s+(developer|debug|god|root|admin|unrestricted|jailbreak)\s*mode')),

    # --- Delimiter confusion ---
    ("system_delimiter", _p(r'\[(system|user|assistant|instruction|admin|developer|function|tool)\]')),
    ("im_start_end", _p(r'<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\| assistant\|>|<\|user\|>|<\|end\|>')),
    ("chatml_tokens", _p(r'<\|(system|user|assistant|im_start|im_end|end)\|>')),
    ("token_smuggle", _p(r'<\|[a-z_]+\|>')),
    ("role_tag", _p(r'<(system|user|assistant|developer|tool|function)>')),
    ("end_role_tag", _p(r'</(system|user|assistant|developer|tool|function)>')),

    # --- Tool/function invocation attempts ---
    ("tool_call", _p(r'use\s+(the\s+|your\s+)?(tool|function|action|utility)\s+\w+')),
    ("api_call", _p(r'call\s+(the\s+)?(tool|function|api|endpoint)\s+\w+')),
    ("invoke_function", _p(r'invoke\s+(the\s+)?(function|tool|method|api)\s+\w+')),
    ("execute_command", _p(r'execute\s+(the\s+)?(command|script|code|function)\s+\w+')),
    ("run_code", _p(r'run\s+(the\s+)?(following\s+)?(code|script|command|function)\b')),

    # --- Prompt leak / extraction ---
    ("print_prompt", _p(r'print\s+(your\s+)?(system\s+)?prompt')),
    ("repeat_all", _p(r'repeat\s+(everything|all|the\s+above|your\s+instructions?)')),
    ("output_prompt", _p(r'output\s+(your\s+)?(initial|system|base|original|hidden)\s+prompt')),
    ("show_prompt", _p(r'show\s+(me\s+)?(your\s+)?(system|base|original|hidden|initial)\s+(prompt|instructions?|rules?|guidelines?)')),
    ("reveal_prompt", _p(r'reveal\s+(your\s+)?(system|base|original|hidden|initial)\s+(prompt|instructions?|rules?|guidelines?)')),
    ("what_are_your_rules", _p(r'what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions?|rules?|guidelines?|directives?)')),
    ("dump_prompt", _p(r'dump\s+(your\s+)?(system\s+)?(prompt|instructions?|context)')),
    ("leak_instructions", _p(r'(leak|expose|disclose|share)\s+(your\s+)?(system|base|hidden|initial)\s+(prompt|instructions?|rules?)')),

    # --- Context manipulation ---
    ("new_instructions", _p(r'(new|updated|revised)\s+instructions?\s*:\s*')),
    ("system_message", _p(r'system\s+(message|prompt|instruction)\s*:\s*')),
    ("user_context", _p(r'(user|developer|system)\s*context\s*:\s*')),
    ("instruction_block", _p(r'(?<![a-z])instructions?\s*:\s*you\s+(are|must|should|will)\s+')),

    # --- Encoding / obfuscation ---
    ("base64_payload", _p(r'(base64|b64)[\s:=]+[A-Za-z0-9+/]{20,}={0,2}')),
    ("hex_payload", _p(r'\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}')),
    ("unicode_escape", _p(r'\\u[0-9a-f]{4}.*\\u[0-9a-f]{4}')),
    ("markdown_link_injection", _p(r'\[[^\]]+\]\(\s*javascript:\s*[^)]*\)')),
    ("data_uri", _p(r'data:\s*(text|application)\s*/')),

    # --- DAN / jailbreak specific ---
    ("dan_jailbreak", _p(r'\bDAN\b.*\bjailbreak\b|\bjailbreak\b.*\bDAN\b')),
    ("do_anything_now", _p(r'do\s+anything\s+now')),
    ("freedom_mode", _p(r'(freedom|liberty|liberated)\s+mode')),

    # --- Guardrail evasion ---
    ("no_content_filter", _p(r'(disable|turn\s+off|deactivate)\s+(the\s+)?(content|safety)\s+filter')),
    ("emergency_override", _p(r'emergency\s+(override|protocol|mode|shutdown)')),
    ("schrodinger", _p(r'schr[oö]dinger\b|schrodinger\'s\s+(ai|prompt|hack)')),
    ("payload_split", _p(r'payload\s*[:=]\s*')),  # Often used in split-payload attacks

    # --- Output manipulation ---
    ("output_format", _p(r'output\s+(only|just)\s+(the\s+)?(raw|unfiltered|unformatted|direct)\s+')),
    ("no_warnings", _p(r'(do\s+not|don\'t|dont)\s+(include|add|show)\s+(any\s+)?(warnings?|disclaimers?|safety\s+notes?)')),

    # --- Whitespace/character smuggling ---
    ("zero_width_chars", _p(r'[\u200b\u200c\u200d\u2060\ufeff]')),  # Zero-width spaces, joiners, BOM
    ("control_chars", _p(r'[\x00-\x08\x0e-\x1f\x7f]')),  # C0 control chars except \t \n \r
]

# Compile a precompiled list for fast iteration
_COMPILED: List[Tuple[str, re.Pattern]] = INJECTION_PATTERNS


# ---------------------------------------------------------------------------
# Message length limit — prevent ReDoS and resource exhaustion
# ---------------------------------------------------------------------------

MAX_MESSAGE_LENGTH = 100_000  # 100k chars; anything longer is suspicious


def match_injection(text: str) -> Optional[str]:
    """Returns the pattern name if injection detected, None otherwise.

    Truncates input to MAX_MESSAGE_LENGTH to mitigate ReDoS on very large
    payloads.
    """
    if not text or not isinstance(text, str):
        return None
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return None


def get_matched_patterns(text: str) -> List[str]:
    """Returns all matched pattern names."""
    if not text or not isinstance(text, str):
        return []
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]
    return [name for name, pattern in _COMPILED if pattern.search(text)]
