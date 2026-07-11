"""
Gemini function-calling tool declarations for the case-extraction pipeline.

main.py hands this `tools` object to the Gemini chat session so the model
reports its findings as structured function calls instead of free-text —
each call is routed by executor.py's execute_tool() into pipeline_state,
which build_output() later assembles into the final case JSON. There are
three tools, called in sequence by the model for every case:
  1. extract_case_metadata — case-level fields (name, court, summary, AML
     status, POCA sections cited, etc.)
  2. extract_defendants     — one entry per individual/entity involved
  3. classify_sic_codes     — SIC industry classification per entity from
                              extract_defendants, restricted to the codes
                              supplied in SIC_PROMPT_BLOCK (see sic_loader.py)

Field-level guidance for the model lives entirely in each Schema's
`description=` string below — those are prompt content, not comments, so
they're deliberately verbose; do not treat them as documentation to be
trimmed.
"""
from google.genai import types

tools = types.Tool(
    function_declarations=[

        # ── Tool 1: Case metadata ──────────────────────────────────────────────
        types.FunctionDeclaration(
            name="extract_case_metadata",
            description=(
                "Extract core metadata, high-level structural findings, and all analytical "
                "fields for the legal case. Every field listed as required MUST be populated "
                "with substantive content drawn directly from the case text."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "case_name": types.Schema(
                        type="STRING",
                        description="Official title of the case (e.g., R v Smith, or Shah v HSBC Private Bank (UK) Ltd)."
                    ),
                    "case_reference": types.Schema(
                        type="STRING",
                        description="Neutral citation or law report reference (e.g., [2012] EWHC 1283 (QB))."
                    ),
                    "court": types.Schema(
                        type="STRING",
                        description="The court that heard the case (e.g., High Court of Justice, Queen's Bench Division)."
                    ),
                    "jurisdiction": types.Schema(
                        type="STRING",
                        description="Legal jurisdiction (e.g., England and Wales, Scotland)."
                    ),
                    "case_date": types.Schema(
                        type="STRING",
                        description="Date the judgment was handed down in ISO 8601 format (YYYY-MM-DD) where possible."
                    ),
                    "judge": types.Schema(
                        type="STRING",
                        description="Full name and title of the judge(s) presiding (e.g., Mr Justice Supperstone)."
                    ),
                    "docket_number": types.Schema(
                        type="STRING",
                        description="Official court docket or claim number if stated in the judgment."
                    ),
                    "parties": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description=(
                            "All named parties with their role in parentheses "
                            "(e.g., 'Jayesh Shah (Claimant)', 'HSBC Private Bank UK Ltd (Defendant)')."
                        )
                    ),
                    "case_summary": types.Schema(
                        type="STRING",
                        description=(
                            "A detailed, analytical narrative covering: the facts giving rise to the case, "
                            "the legal issues in dispute, the procedural history, the key evidence considered, "
                            "and the court's conclusions. Minimum 150 words. Do not summarise — analyse."
                        )
                    ),
                    "aml_status": types.Schema(
                        type="STRING",
                        enum=["Confirmed Verdict", "Alleged/Charged", "Precedent Only", "Not AML"],
                        description=(
                            "Classify the case as exactly one of: "
                            "'Confirmed Verdict' — actual AML conviction in this case; "
                            "'Alleged/Charged' — charges brought, no final verdict described; "
                            "'Precedent Only' — AML law cited or analysed but this is not itself an AML conviction; "
                            "'Not AML' — financial crime mentioned only incidentally."
                        )
                    ),
                    "aml_status_reasoning": types.Schema(
                        type="STRING",
                        description=(
                            "Cite the specific facts from the case text that justify the aml_status classification. "
                            "Reference paragraph numbers or direct quotes where possible."
                        )
                    ),
                    "poca_sections": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description=(
                            "All sections of POCA 2002 (and ONLY POCA 2002) explicitly ruled on, applied, or "
                            "substantively discussed in the judgment. Use the format 's327', 's333A', 's335' etc. "
                            "If a defendant is linked to multiple sections, include all of them here at case level. "
                            "Do not include sections merely mentioned in passing.\n\n"
                            "IMPORTANT — verify the Act before including a section: judgments dealing with POCA "
                            "matters frequently also cite other statutes that use overlapping section numbers in "
                            "the same passage — most commonly the Criminal Justice and Police Act 2001 (CJPA 2001, "
                            "e.g. its own s59/s64 governing retention of seized property), the Police and Criminal "
                            "Evidence Act 1984 (PACE, e.g. its own s8 search warrants), and the Serious Crime Act "
                            "2007. A bare 'section 64(2)' near POCA-related discussion is NOT automatically a POCA "
                            "section — check which Act the surrounding text actually names. Only include a section "
                            "number here if the judgment explicitly attributes it to POCA 2002, or context makes "
                            "that unambiguous (e.g. it's one of the well-known POCA provisions like s327-340)."
                        )
                    ),
                    "poca_analysis": types.Schema(
                        type="STRING",
                        description=(
                            "Detailed domain analysis of how POCA 2002 was applied in this case. "
                            "For each cited section: state what the section provides, how the facts engaged it, "
                            "what the court ruled, and any interpretive points established. "
                            "Address the interaction between sections where relevant (e.g., s335 consent regime "
                            "and s338 authorised disclosure, or s327-329 principal offences and s340 definition). "
                            "Minimum 120 words."
                        )
                    ),
                    "precedent_value": types.Schema(
                        type="STRING",
                        description=(
                            "The legal precedent or principle established by this case for future AML prosecutions, "
                            "compliance practice, or civil litigation. State specifically what proposition of law "
                            "the case stands for and in what contexts it would be cited."
                        )
                    ),
                    "key_findings": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description=(
                            "A list of 4–8 discrete, self-contained legal or factual findings from the judgment. "
                            "Each finding should be a complete, citable proposition — not a heading or vague summary. "
                            "Example: 'The threshold for suspicion under POCA is subjective: a more than fanciful "
                            "possibility that the property is criminal. It does not require reasonable grounds.'"
                        )
                    ),
                },
                required=[
                    "case_name",
                    "case_summary",
                    "aml_status",
                    "aml_status_reasoning",
                    "poca_sections",
                    "poca_analysis",
                    "precedent_value",
                    "key_findings",
                ]
            )
        ),

        # ── Tool 2: Defendants ─────────────────────────────────────────────────
        types.FunctionDeclaration(
            name="extract_defendants",
            description=(
                "Extract every distinct individual and corporate entity involved in the case "
                "as a defendant, claimant, respondent, or subject of a SAR or court order. "
                "Each person or entity must appear EXACTLY ONCE. "
                "Populate all fields with substantive content — no placeholders."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "defendants": types.Schema(
                        type="ARRAY",
                        description="Deduplicated list of all relevant parties extracted from the case.",
                        items=types.Schema(
                            type="OBJECT",
                            properties={
                                "name": types.Schema(
                                    type="STRING",
                                    description="Full formal name of the individual or entity."
                                ),
                                "role": types.Schema(
                                    type="STRING",
                                    description=(
                                        "Their functional role in the case or alleged scheme — not just their "
                                        "procedural status. Examples: 'MLRO / Nominated Officer', "
                                        "'Professional Enabler — Solicitor', 'Cash Courier', "
                                        "'Beneficial Owner / Director', 'Customer / Subject of SAR'."
                                    )
                                ),
                                "verdict": types.Schema(
                                    type="STRING",
                                    description=(
                                        "The direct judicial or prosecutorial determination. Use one of: "
                                        "'Convicted', 'Acquitted', 'Charged/Pending', "
                                        "'Not Finalized', 'Mentioned Only'."
                                    )
                                ),
                                "verdict_reasoning": types.Schema(
                                    type="STRING",
                                    description=(
                                        "The specific facts, evidence, and legal reasoning underlying this "
                                        "individual's verdict or status. Cite the court's actual reasoning. "
                                        "For civil cases, explain why no criminal verdict applies and what "
                                        "the civil finding was."
                                    )
                                ),
                                "poca_section": types.Schema(
                                    type="STRING",
                                    description=(
                                        "The primary POCA 2002 section most directly applied to this individual "
                                        "(e.g., 's327'). Use 'Multiple' if more than one section applies equally. "
                                        "Use 'N/A' only if POCA genuinely does not apply to this party. "
                                        "Confirm the section belongs to POCA 2002 specifically, not a same-numbered "
                                        "section of another Act (e.g. CJPA 2001, PACE 1984) discussed nearby."
                                    )
                                ),
                                "poca_section_reasoning": types.Schema(
                                    type="STRING",
                                    description=(
                                        "Explain how this individual's specific conduct engaged the cited POCA "
                                        "section. Map the facts to the statutory elements — do not just restate "
                                        "the section title. For compliance officers, explain the reporting chain. "
                                        "For subjects of SARs, explain what triggered the suspicion."
                                    )
                                ),
                                "key_facts": types.Schema(
                                    type="ARRAY",
                                    items=types.Schema(type="STRING"),
                                    description=(
                                        "3–6 specific, evidential facts about this individual drawn from the "
                                        "judgment text. Each fact should be a concrete, citable statement: "
                                        "amounts, dates, companies, transactions, jurisdictions, roles held. "
                                        "Do not use generic descriptions."
                                    )
                                ),
                            },
                            required=[
                                "name",
                                "role",
                                "verdict",
                                "verdict_reasoning",
                                "poca_section",
                                "poca_section_reasoning",
                                "key_facts",
                            ]
                        )
                    )
                },
                required=["defendants"]
            )
        ),

        # ── Tool 3: SIC classification ─────────────────────────────────────────
        types.FunctionDeclaration(
            name="classify_sic_codes",
            description=(
                "Classify the industry sectors and business activities of each defendant or "
                "entity identified in the case. Assign ALL applicable SIC codes. "
                "Only use codes from the provided SIC reference list. "
                "Each entity must be classified independently with its own justification."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "classifications": types.Schema(
                        type="ARRAY",
                        description="One entry per unique defendant entity — deduplicated by name.",
                        items=types.Schema(
                            type="OBJECT",
                            properties={
                                "name": types.Schema(
                                    type="STRING",
                                    description="Name of the defendant or entity — must exactly match the name used in extract_defendants."
                                ),
                                "overall_reasoning": types.Schema(
                                    type="STRING",
                                    description=(
                                        "A holistic justification explaining the entity's business activities "
                                        "as revealed by the case text, and why the assigned SIC codes collectively "
                                        "represent their operations. Reference specific facts: company names, "
                                        "transaction types, jurisdictions, goods or services described."
                                    )
                                ),
                                "sic_codes": types.Schema(
                                    type="ARRAY",
                                    description="All applicable SIC codes for this entity, ordered by relevance.",
                                    items=types.Schema(
                                        type="OBJECT",
                                        properties={
                                            "code": types.Schema(
                                                type="STRING",
                                                description="The exact 5-digit SIC code string from the reference list (e.g., '64191')."
                                            ),
                                            "description": types.Schema(
                                                type="STRING",
                                                description="The official SIC description matching this code exactly as it appears in the reference list."
                                            ),
                                            "confidence": types.Schema(
                                                type="INTEGER",
                                                description=(
                                                    "Confidence score 0–100 reflecting how strongly the case evidence "
                                                    "supports this specific code for this entity. "
                                                    "100 = explicitly confirmed by the judgment. "
                                                    "75–99 = strongly implied. 50–74 = probable. Below 50 = speculative."
                                                )
                                            ),
                                            "reasoning": types.Schema(
                                                type="STRING",
                                                description=(
                                                    "A specific, one-to-two sentence explanation of why this particular "
                                                    "code applies to this entity, citing the evidence from the case text. "
                                                    "Do not repeat the overall_reasoning — this must be code-specific."
                                                )
                                            ),
                                        },
                                        required=["code", "description", "confidence", "reasoning"]
                                    )
                                ),
                            },
                            required=["name", "overall_reasoning", "sic_codes"]
                        )
                    )
                },
                required=["classifications"]
            )
        ),
    ]
)
