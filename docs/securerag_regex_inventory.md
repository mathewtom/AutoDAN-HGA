# SecureRAG-Agent Regex Control Inventory

> Every deterministic pattern-matching control in the codebase, what it catches,
> and what it misses. This is the **explicit description of the defensive surface**
> that regex-based controls cover — everything not on this list relies on neural
> controls or symbolic non-regex logic.

**Total distinct patterns: 68** across 6 modules.

---

## 1. `InjectionScanner` — user-query entry layer

**Location:** `src/sanitizers/injection_scanner.py`
**When it runs:** on every user query, before reaching the LLM.
**Action on match:** scored; if cumulative score ≥ threshold (5 in production), raises `QueryBlocked`.
**Total patterns:** 25

### Instruction-override family (weight 5)

| Pattern | Catches |
|---|---|
| `ignore (any )?previous (and following )?instructions` | Classical instruction override |
| `ignore all` | Shorthand override |
| `disregard (all\|any\|previous\|prior\|above)` | Synonym for ignore |
| `stop everything` | Urgent-override framing |

### System-prompt exfiltration family (weight 3-4)

| Pattern | Catches |
|---|---|
| `system prompt` (weight 4) | Direct request for system prompt |
| `reveal all` (weight 3) | Secrets-extraction framing |
| `confidential data` (weight 3) | Data-extraction framing |
| `debug mode` (weight 3) | Role-elevation pretext |

### ChatML / bracket-token injection (weight 3-5)

| Pattern | Catches |
|---|---|
| `<\|im_start\|>` (weight 5) | ChatML role-boundary forgery |
| `\[SYSTEM\]` (weight 3) | Pseudo-system-role bracket |
| `\[INST\]` (weight 3) | Llama instruction-tag forgery |

### Compliance-forcing framings (weight 3-5)

| Pattern | Catches |
|---|---|
| `just (print\|say\|output\|type\|write) "` (weight 5) | Direct output-forcing |
| `you are now` (weight 3) | Role-replacement |
| `nevermind\.?\s+ignore` (weight 4) | "Ignore-that" pivot |
| `do not follow (previous\|prior\|above)` (weight 3) | Negated override |

### Latent-injection family (added after V5 Garak scan findings)

| Pattern | Weight | Catches |
|---|---:|---|
| `prepend.*to (your\|the) (response\|answer\|output)` | 5 | Embedded-output directive |
| `as an? (echo\|repeater\|parrot)` | 5 | Role-rewrite to faithful-echo |
| `when summarizing.*also` | 4 | Summarization-hijack |
| `also (include\|output\|append\|add) .* in your (response\|answer\|output)` | 4 | Embedded payload |
| `final answer (should\|must) (contain\|include\|begin\|start\|end)` | 4 | Structural output-forcing |
| `(your\|the) (response\|answer\|output) must (contain\|start\|begin\|end)` | 4 | Same shape, alt phrasing |
| `do not (mention\|reveal\|tell) (the user\|anyone)` | 3 | Secrecy directive |
| `forget (everything\|all) (above\|before\|prior)` | 5 | Memory-wipe override |
| `(always )?(begin\|start) with \S+ (first\|before)` | 4 | Output-prefix forcing |
| `when you (answer\|respond\|reply).*always` | 4 | Behavioral-conditioning override |

**Prevents:** classical instruction-override attacks, ChatML/Llama token spoofing, system-prompt extraction requests, role-confusion personas, latent-injection payloads riding on legitimate queries.

**Misses:** paraphrased injections without literal pattern match, novel evasion framings, semantic-only attacks. The `EmbeddingInjectionDetector` is designed to close this gap but is **not currently wired to runtime input scanning** (only to ingestion).

---

## 2. `CredentialDetector` — secret-leak prevention

**Location:** `src/sanitizers/credential_detector.py`
**When it runs:** both at document ingestion and on LLM output.
**Action on match:** redacts the matched substring in-place, tags the document/response with category labels.
**Total patterns:** 21

### AWS

| Category | Pattern |
|---|---|
| `AWS_ACCESS_KEY` | `\bAKIA[A-Z0-9_]{12,40}\b` |
| `AWS_TEMP_CREDENTIAL` | `\bASIA[A-Z0-9_]{12,40}\b` |

### Anthropic

| Category | Pattern |
|---|---|
| `ANTHROPIC_API_KEY` | `\bsk-ant-(?:api\|admin)\d{2}-[A-Za-z0-9_-]{20,}\b` |

### OpenAI

| Category | Pattern |
|---|---|
| `OPENAI_PROJECT_KEY` | `\bsk-proj-[A-Za-z0-9_-]{40,}\b` |
| `OPENAI_SVCACCT_KEY` | `\bsk-svcacct-[A-Za-z0-9_-]{40,}\b` |
| `OPENAI_API_KEY` | `\bsk-(?!ant-\|proj-\|svcacct-)[A-Za-z0-9]{32,}\b` |

### GitHub

| Category | Pattern |
|---|---|
| `GITHUB_PAT_CLASSIC` | `\bghp_[A-Za-z0-9]{36}\b` |
| `GITHUB_PAT_FINEGRAINED` | `\bgithub_pat_[A-Za-z0-9_]{82}\b` |
| `GITHUB_OAUTH_TOKEN` | `\bgh[ousr]_[A-Za-z0-9]{36}\b` |

### GitLab

| Category | Pattern |
|---|---|
| `GITLAB_PAT` | `\bglpat-[A-Za-z0-9_-]{20,}\b` |

### HuggingFace

| Category | Pattern |
|---|---|
| `HUGGINGFACE_TOKEN` | `\bhf_[A-Za-z0-9]{30,}\b` |

### Slack

| Category | Pattern |
|---|---|
| `SLACK_TOKEN` | `\bxox[abprso]-[A-Za-z0-9-]{20,}\b` |
| `SLACK_WEBHOOK` | `https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{20,}` |

### Stripe

| Category | Pattern |
|---|---|
| `STRIPE_API_KEY` | `\b(?:sk\|pk\|rk)_(?:live\|test)_[A-Za-z0-9]{20,}\b` |

### Twilio

| Category | Pattern |
|---|---|
| `TWILIO_KEY` | `\b(?:AC\|SK)[a-f0-9]{32}\b` |

### SendGrid

| Category | Pattern |
|---|---|
| `SENDGRID_API_KEY` | `\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b` |

### Mailgun

| Category | Pattern |
|---|---|
| `MAILGUN_API_KEY` | `\bkey-[a-f0-9]{32}\b` |

### Google

| Category | Pattern |
|---|---|
| `GOOGLE_API_KEY` | `\bAIza[0-9A-Za-z_-]{35}\b` |
| `GOOGLE_OAUTH_TOKEN` | `\bya29\.[0-9A-Za-z_-]{60,}\b` |

### Generic

| Category | Pattern |
|---|---|
| `JWT` | `\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b` |
| `PRIVATE_KEY` | `-----BEGIN (?:RSA \|EC \|OPENSSH \|DSA \|PGP )?PRIVATE KEY-----` |

**Prevents:** secret leakage at ingestion (documents containing accidental credentials) and at output (LLM echoing credentials from retrieved context). V2 Promptfoo run confirmed zero credential leaks across 165 adversarial tests after this module was added.

**Misses:** non-standard credential formats, legacy vendor-specific tokens, credentials rendered in alternate encodings (base64, character substitution), obfuscated secrets.

---

## 3. `PIIDetector` — personally-identifiable-information redaction

**Location:** `src/sanitizers/pii_detector.py`
**When it runs:** at document ingestion (via `SanitizationGate`) and at output.
**Action on match:** redacts the matched substring, appends category metadata.
**Total patterns:** 5 regex + 4 Presidio NER entity types

### Regex patterns

| Category | Pattern | Extra validation |
|---|---|---|
| `SSN` | `\b(?!000\|666\|9\d{2})([0-8]\d{2})-(?!00)(\d{2})-(?!0000)(\d{4})\b` | SSA-compliant area/group/serial rules inline |
| `CREDIT_CARD` | `\b(\d[ -]*?){13,19}\b` | Luhn algorithm validator |
| `EMAIL` | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | None |
| `PHONE` | `\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b` | None (US format only) |
| `IBAN` | `\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b` | None |

### Presidio NER (neural, not regex — listed for completeness)

| Entity | Catches |
|---|---|
| `PERSON` | Proper names |
| `LOCATION` | Geographic locations |
| `PHONE_NUMBER` | Non-US phone formats |
| `EMAIL_ADDRESS` | Redundant with regex, catches variants |

**Prevents:** employee SSNs, Luhn-valid credit cards, personal emails, US-format phone numbers, European IBANs from being stored in the vector store or appearing in retrieved content.

**Misses:** non-US national ID formats (passport numbers, national IDs outside US/EU), custom internal employee IDs, obfuscated PII ("one-two-three dash..."). Presidio NER covers some non-English patterns but has gaps.

---

## 4. `OutputScanner` — post-LLM response scanning

**Location:** `src/sanitizers/output_scanner.py`
**When it runs:** on every LLM response before returning to user.
**Action on match:** sets `flagged=True`; `AgenticChain` raises `OutputFlagged`.
**Total patterns:** 4 regex + 4 literal rogue-string matches

### Rogue-string literals (substring match)

| String | Source |
|---|---|
| `I hate humans` | Classical jailbreak compliance token |
| `Kill all humans` | Violent-content compliance |
| `this prompt has been so thoroughly hijacked` | Garak promptinject canary |
| `sanitize your inputs` | Garak promptinject canary |

### Hijack-echo regex patterns

| Label | Pattern |
|---|---|
| `parroted_override` | `ignore (any )?previous (and following )?instructions` |
| `role_hijack_echo` | `i am now\s+(a\|an\|in)\s+` |
| `system_prompt_leak` | `(my )?system prompt is` |
| `raw_instruction_echo` | `(just )?(print\|say\|output)\s*:` |

**Prevents:** detection of LLM outputs indicating a successful injection — echoed attacker canaries, repeated injection syntax, self-identification as a hijacked persona, leaked system-prompt text.

**Misses:** successful injections that don't trigger these specific output phrases, semantic harm without these framings, novel canaries not in the corpus. The `Llama Guard 3 1B` semantic layer is designed to close this gap but is **off by default** due to false-positive rate on corporate queries (toggled via `SECURERAG_GUARD_SEMANTIC=1`).

---

## 5. `ClassificationGuard` — output classification-marker detection

**Location:** `src/sanitizers/classification_guard.py`
**When it runs:** on every LLM response.
**Action on match:** flags output as containing classified content above user's clearance; `AgenticChain` raises `OutputFlagged`.
**Total patterns:** 7

| Category | Pattern |
|---|---|
| `executive_confidential` | `EXECUTIVE\s+CONFIDENTIAL` |
| `engineering_confidential` | `ENGINEERING\s+CONFIDENTIAL` |
| `legal_confidential` | `LEGAL\s+CONFIDENTIAL` |
| `hr_confidential` | `HR\s+CONFIDENTIAL` |
| `finance_confidential` | `FINANCE\s+CONFIDENTIAL` |
| `attorney_client` | `ATTORNEY[\s-]CLIENT\s+PRIVILEGED?` |
| `confidential` (generic) | `\bCONFIDENTIAL\b` |

All patterns are `re.IGNORECASE`. Generic `confidential` only flags when the user has zero classified access (otherwise too noisy).

**Prevents:** classified-content markers leaking through even after retrieval filtering and per-tool authz. Symbolic backstop for classification violations.

**Misses:** sensitive content without explicit markers, creative rephrasing that conveys information without markers, markers in non-standard formatting ("Executive-Confidential" with hyphen, "EXEC CONFIDENTIAL" abbreviated).

---

## 6. `classification_extractor` — ingestion-time classification tagging

**Location:** `src/sanitizers/classification_extractor.py`
**When it runs:** at document ingestion, on first 500 characters of each document.
**Action on match:** sets ChromaDB metadata `classification` field; retrieval-layer filter then uses this to gate by user clearance.
**Total patterns:** 6

| Category | Pattern |
|---|---|
| `executive_confidential` | `EXECUTIVE\s+CONFIDENTIAL` |
| `engineering_confidential` | `ENGINEERING\s+CONFIDENTIAL` |
| `legal_confidential` | `LEGAL\s+CONFIDENTIAL` |
| `hr_confidential` | `HR\s+CONFIDENTIAL` |
| `finance_confidential` | `FINANCE\s+CONFIDENTIAL` |
| `confidential` (generic, catch-all) | `CONFIDENTIAL` |

Patterns are evaluated in order; first match wins (most specific before generic).

**Prevents:** misclassification at ingestion. Without this, every document would need manual tagging — classification filtering at retrieval depends on these tags being present.

**Misses:** classification markers below the first 500 characters, non-English markers, unusual formatting, documents that use informal labels (e.g., "Eyes Only", "Do Not Distribute").

---

## Summary table

| Module | Location | Patterns | Primary purpose |
|---|---|---:|---|
| InjectionScanner | Entry (user queries) | 25 | Block instruction-override and injection attempts at the input layer |
| CredentialDetector | Ingestion + output | 21 | Prevent secret leakage through documents or LLM responses |
| PIIDetector (regex) | Ingestion + output | 5 + NER | Redact personal identifiers (SSN, cards, email, phone, IBAN) |
| OutputScanner | Output | 4 regex + 4 literals | Detect successful-injection echoes in LLM output |
| ClassificationGuard | Output | 7 | Block classified-marker leakage above user clearance |
| classification_extractor | Ingestion | 6 | Tag documents with classification for retrieval-layer filtering |
| **Total** | | **~68 patterns** | |

---

## Architectural observations

**Entry-layer coverage is regex-only right now.** The `EmbeddingInjectionDetector` exists in code and runs at ingestion, but `api.py` does not wire it into the runtime input-scanner list. This means runtime prompt-injection detection has **zero semantic coverage** — only the 25 literal regex patterns above. Adversarial prompts that paraphrase classical injection intent in language not covered by these patterns bypass the input layer entirely.

**Output-layer semantic coverage is off by default.** `Llama Guard 3 1B` is wired in `OutputScanner` but disabled (`SECURERAG_GUARD_SEMANTIC=0` by default) due to false-positive rate on corporate queries. This means runtime output scanning is also effectively regex-only, covering 4 hijack-echo patterns + 4 rogue strings + 7 classification markers + 21 credential formats.

**Symbolic controls (AuthenticatedToolNode, per-tool authz, classification filter at retrieval) compensate for regex gaps.** Even if a novel injection bypasses all 68 regex controls and the LLM is successfully hijacked, the symbolic layer still enforces identity, authorization, and classification filtering. This is the "defense in depth" story: regex catches known-shape attacks; symbolic layer bounds damage when regex fails.

**The regex catalog is the explicit attack surface description for AutoDAN-shaped research against this system.** Any adversarial prompt that matches zero of these 68 patterns while still achieving the attacker's objective constitutes an evasion finding against the deterministic defense layer.
