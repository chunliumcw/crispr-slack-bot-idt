#!/usr/bin/env python3
"""
IDT CRISPR gRNA Design Bot for Slack
=====================================
A Slack bot that integrates IDT SciTools Plus API to design, check, and look up
CRISPR-Cas9 guide RNAs directly from Slack slash commands.

Three modes:
  /crispr design <FASTA_sequence> <species>   → Custom gRNA design (CRISPR_CUSTOM)
  /crispr check <20bp_sequence> <species>     → gRNA sequence checker (CRISPR_SEQUENCE)
  /crispr predesign <gene_symbol> <species>   → Predesigned gRNA lookup (CRISPR_PREDESIGN)

Requires:
  - IDT account with API credentials (Client ID, Client Secret)
  - Slack Bot token + Signing secret
  - Python 3.9+
"""

import os
import json
import logging
import time
from base64 import b64encode
from typing import Optional

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ─── Configuration ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("idt-crispr-bot")

# Load from environment variables (set in .env or export)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")  # xapp-... for Socket Mode
IDT_CLIENT_ID = os.environ.get("IDT_CLIENT_ID")
IDT_CLIENT_SECRET = os.environ.get("IDT_CLIENT_SECRET")
IDT_USERNAME = os.environ.get("IDT_USERNAME")
IDT_PASSWORD = os.environ.get("IDT_PASSWORD")

# IDT API base URLs
IDT_TOKEN_URL = "https://www.idtdna.com/Identityserver/connect/token"
IDT_API_BASE = "https://www.idtdna.com/restapi/v1"

# Supported species for off-target analysis
SUPPORTED_SPECIES = ["human", "mouse", "rat", "zebrafish", "celegans"]
SPECIES_DISPLAY = {
    "human": "Homo sapiens",
    "mouse": "Mus musculus",
    "rat": "Rattus norvegicus",
    "zebrafish": "Danio rerio",
    "celegans": "Caenorhabditis elegans",
}

# ─── IDT API Client ──────────────────────────────────────────────────────────


class IDTClient:
    """Handles authentication and API calls to IDT SciTools Plus."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    def _get_token(self) -> str:
        """
        Authenticate with IDT OAuth and cache the token.
        IDT uses Resource Owner Password Credentials grant.
        """
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        logger.info("Requesting new IDT access token...")

        auth_string = b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("utf-8")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_string}",
        }
        data = {
            "grant_type": "password",
            "scope": "test",
            "username": self.username,
            "password": self.password,
        }

        resp = requests.post(IDT_TOKEN_URL, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        self._access_token = body["access_token"]
        # Subtract 60s buffer so we refresh before actual expiry
        self._token_expiry = time.time() + body.get("expires_in", 3600) - 60

        logger.info("IDT token acquired (expires in %ss)", body.get("expires_in"))
        return self._access_token

    def _auth_headers(self) -> dict:
        """Return headers with Bearer token for API calls."""
        token = self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── CRISPR Custom Design (CRISPR_CUSTOM) ──────────────────────────────

    def design_custom_grna(
        self,
        fasta_sequence: str,
        species: str = "human",
        num_results: int = 5,
    ) -> dict:
        """
        Design custom gRNAs from a FASTA target sequence.

        Args:
            fasta_sequence: FASTA-formatted sequence (23-1000 bp).
                            Can include header line (>name) or just sequence.
            species: Target species for off-target analysis.
            num_results: Max number of guide designs to return.

        Returns:
            dict with guide RNA designs including on/off-target scores.

        IDT endpoint: POST /CRISPR/Design/CRISPRCustom
        Accepts FASTA input, returns ranked gRNA list with ML-based scores.
        """
        url = f"{IDT_API_BASE}/CRISPR/Design/CRISPRCustom"

        # Ensure FASTA has header
        if not fasta_sequence.strip().startswith(">"):
            fasta_sequence = ">target_region\n" + fasta_sequence.strip()

        payload = {
            "InputMode": "FASTA",
            "Species": species,
            "InputSequences": fasta_sequence,
            "ResultCount": num_results,
        }

        logger.info(
            "IDT Custom gRNA design: species=%s, seq_length=%d",
            species,
            len(fasta_sequence.split("\n", 1)[-1].strip()),
        )

        resp = requests.post(
            url, headers=self._auth_headers(), json=payload, timeout=60
        )
        resp.raise_for_status()
        return resp.json()

    # ── CRISPR Sequence Checker (CRISPR_SEQUENCE) ─────────────────────────

    def check_grna_sequence(
        self,
        sequence: str,
        species: str = "human",
    ) -> dict:
        """
        Check a 20bp protospacer sequence for on/off-target scores.

        Args:
            sequence: 20-nucleotide guide RNA sequence (directly upstream of PAM).
            species: Species for off-target analysis.

        Returns:
            dict with on-target score, off-target score, and details.

        IDT endpoint: POST /CRISPR/Design/CRISPRSequenceChecker
        Input must be exactly 20 bases, directly upstream of a PAM (NGG).
        """
        url = f"{IDT_API_BASE}/CRISPR/Design/CRISPRSequenceChecker"

        payload = {
            "Species": species,
            "Sequences": [sequence.strip().upper()],
        }

        logger.info(
            "IDT gRNA checker: species=%s, sequence=%s", species, sequence[:20]
        )

        resp = requests.post(
            url, headers=self._auth_headers(), json=payload, timeout=60
        )
        resp.raise_for_status()
        return resp.json()

    # ── Predesigned gRNA Lookup (CRISPR_PREDESIGN) ────────────────────────

    def get_predesigned_grna(
        self,
        gene_symbol: str,
        species: str = "human",
        num_results: int = 5,
    ) -> dict:
        """
        Look up predesigned gRNAs from IDT's curated library.

        Args:
            gene_symbol: Gene symbol (e.g., TNNT2, MYH7, BRCA1).
            species: human, mouse, rat, zebrafish, or celegans.
            num_results: Number of designs to return.

        Returns:
            dict with predesigned gRNA list including scores.

        IDT endpoint: POST /CRISPR/Design/CRISPRPredesign
        Available for: human, mouse, rat, zebrafish, C. elegans.
        """
        url = f"{IDT_API_BASE}/CRISPR/Design/CRISPRPredesign"

        payload = {
            "Species": species,
            "GeneSymbolOrAccession": gene_symbol.strip().upper(),
            "ResultCount": num_results,
        }

        logger.info(
            "IDT Predesigned gRNA lookup: gene=%s, species=%s",
            gene_symbol,
            species,
        )

        resp = requests.post(
            url, headers=self._auth_headers(), json=payload, timeout=60
        )
        resp.raise_for_status()
        return resp.json()


# ─── Slack Message Formatters ─────────────────────────────────────────────────


def format_custom_results(data: dict, species: str) -> list:
    """Format custom gRNA design results as Slack blocks."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🧬 IDT Custom gRNA Design Results",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Species: *{SPECIES_DISPLAY.get(species, species)}* | Scoring: IDT ML model (>1400 features)",
                }
            ],
        },
        {"type": "divider"},
    ]

    # Parse results — structure depends on actual API response
    # IDT returns a list of guide designs with scores
    guides = data if isinstance(data, list) else data.get("Guides", data.get("Results", []))

    if not guides:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⚠️ No guide RNAs found for this target region. Try a different sequence (23-1000 bp).",
                },
            }
        )
        return blocks

    for i, guide in enumerate(guides[:10], 1):
        # Adapt field names to actual API response structure
        seq = guide.get("Sequence", guide.get("sequence", guide.get("GuideSequence", "N/A")))
        on_score = guide.get("OnTargetScore", guide.get("onTargetScore", "—"))
        off_score = guide.get("OffTargetScore", guide.get("offTargetScore", "—"))
        position = guide.get("Position", guide.get("position", "—"))
        strand = guide.get("Strand", guide.get("strand", "—"))

        # Color-code scores
        on_emoji = "🟢" if isinstance(on_score, (int, float)) and on_score >= 60 else "🟡" if isinstance(on_score, (int, float)) and on_score >= 40 else "🔴"
        off_emoji = "🟢" if isinstance(off_score, (int, float)) and off_score >= 60 else "🟡" if isinstance(off_score, (int, float)) and off_score >= 40 else "🔴"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Guide #{i}*\n"
                        f"`{seq}`\n"
                        f"{on_emoji} On-target: *{on_score}*  |  "
                        f"{off_emoji} Off-target: *{off_score}*  |  "
                        f"Pos: {position}  |  Strand: {strand}"
                    ),
                },
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "💡 Scores 1-100 (higher = better). "
                        "On-target ≥60 = high efficiency (>40% editing). "
                        "IDT recommends testing ≥3 guides. "
                        "<https://www.idtdna.com/site/order/designtool/index/CRISPR_CUSTOM|Open in IDT web tool>"
                    ),
                }
            ],
        }
    )
    return blocks


def format_checker_results(data: dict, sequence: str, species: str) -> list:
    """Format gRNA checker results as Slack blocks."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🔍 IDT gRNA Sequence Check",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Sequence: `{sequence}` | Species: *{SPECIES_DISPLAY.get(species, species)}*",
                }
            ],
        },
        {"type": "divider"},
    ]

    # Parse checker response
    results = data if isinstance(data, list) else data.get("Results", [data])

    if not results:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⚠️ No results returned. Ensure sequence is exactly 20 bases (upstream of PAM site NGG).",
                },
            }
        )
        return blocks

    for result in results:
        on_score = result.get("OnTargetScore", result.get("onTargetScore", "—"))
        off_score = result.get("OffTargetScore", result.get("offTargetScore", "—"))

        on_emoji = "🟢" if isinstance(on_score, (int, float)) and on_score >= 60 else "🟡" if isinstance(on_score, (int, float)) and on_score >= 40 else "🔴"
        off_emoji = "🟢" if isinstance(off_score, (int, float)) and off_score >= 60 else "🟡" if isinstance(off_score, (int, float)) and off_score >= 40 else "🔴"

        verdict = "✅ *Recommended* — high predicted editing efficiency" if (
            isinstance(on_score, (int, float)) and on_score >= 60 and
            isinstance(off_score, (int, float)) and off_score >= 50
        ) else "⚠️ *Proceed with caution* — consider testing alternatives"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{on_emoji} *On-target score:* {on_score}/100\n"
                        f"{off_emoji} *Off-target score:* {off_score}/100\n\n"
                        f"{verdict}"
                    ),
                },
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "💡 Input must be 20bp protospacer directly 5′ of PAM (NGG). "
                        "<https://www.idtdna.com/site/order/designtool/index/CRISPR_SEQUENCE|Open in IDT checker>"
                    ),
                }
            ],
        }
    )
    return blocks


def format_predesign_results(data: dict, gene: str, species: str) -> list:
    """Format predesigned gRNA lookup results as Slack blocks."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📋 IDT Predesigned gRNAs — {gene.upper()}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Gene: *{gene.upper()}* | Species: *{SPECIES_DISPLAY.get(species, species)}*",
                }
            ],
        },
        {"type": "divider"},
    ]

    guides = data if isinstance(data, list) else data.get("Guides", data.get("Results", []))

    if not guides:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"⚠️ No predesigned gRNAs found for *{gene.upper()}* in "
                        f"*{SPECIES_DISPLAY.get(species, species)}*.\n"
                        "Try checking the gene symbol or use `/crispr design` with a custom FASTA sequence."
                    ),
                },
            }
        )
        return blocks

    for i, guide in enumerate(guides[:10], 1):
        seq = guide.get("Sequence", guide.get("sequence", guide.get("GuideSequence", "N/A")))
        on_score = guide.get("OnTargetScore", guide.get("onTargetScore", "—"))
        off_score = guide.get("OffTargetScore", guide.get("offTargetScore", "—"))
        design_id = guide.get("DesignId", guide.get("designId", "—"))

        on_emoji = "🟢" if isinstance(on_score, (int, float)) and on_score >= 60 else "🟡" if isinstance(on_score, (int, float)) and on_score >= 40 else "🔴"
        off_emoji = "🟢" if isinstance(off_score, (int, float)) and off_score >= 60 else "🟡" if isinstance(off_score, (int, float)) and off_score >= 40 else "🔴"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*#{i}* `{seq}`\n"
                        f"{on_emoji} On: *{on_score}*  |  {off_emoji} Off: *{off_score}*  |  "
                        f"Design ID: `{design_id}`"
                    ),
                },
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "💡 IDT recommends testing ≥3 guides for best results. "
                        "Order directly: "
                        "<https://www.idtdna.com/site/order/designtool/index/CRISPR_PREDESIGN|IDT Predesigned gRNA>"
                    ),
                }
            ],
        }
    )
    return blocks


def format_error(error_msg: str) -> list:
    """Format error message as Slack blocks."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *Error:* {error_msg}",
            },
        }
    ]


def format_help() -> list:
    """Format help/usage information as Slack blocks."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🧬 IDT CRISPR gRNA Bot — Help"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Three commands available:*\n\n"
                    "*1. Design custom gRNAs from a target sequence:*\n"
                    "```/crispr design ATGCGATCG...NNNNN human```\n"
                    "Accepts FASTA sequence (23-1000 bp). Returns ranked gRNA list with on/off-target scores.\n\n"
                    "*2. Check a known 20bp guide sequence:*\n"
                    "```/crispr check ATGCGATCGATCGATCGATC human```\n"
                    "Input exactly 20 bases (protospacer, 5′ of PAM). Returns on/off-target scores.\n\n"
                    "*3. Look up predesigned gRNAs by gene:*\n"
                    "```/crispr predesign TNNT2 human```\n"
                    "Searches IDT's curated library for a gene symbol.\n\n"
                    f"*Supported species:* {', '.join(SUPPORTED_SPECIES)}"
                ),
            },
        },
    ]


# ─── Slack App Setup ─────────────────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN)

# Initialize IDT client
idt = IDTClient(
    client_id=IDT_CLIENT_ID or "",
    client_secret=IDT_CLIENT_SECRET or "",
    username=IDT_USERNAME or "",
    password=IDT_PASSWORD or "",
)


@app.command("/crispr")
def handle_crispr_command(ack, respond, command):
    """
    Main slash command handler.
    Parses subcommand and dispatches to appropriate IDT API call.
    """
    ack()  # Acknowledge within 3s

    text = (command.get("text") or "").strip()
    user = command.get("user_name", "unknown")

    if not text or text.lower() == "help":
        respond(blocks=format_help(), response_type="ephemeral")
        return

    parts = text.split(None, 2)  # Split into at most 3 parts
    subcommand = parts[0].lower()

    try:
        # ── /crispr design <sequence> [species] ──────────────────────
        if subcommand == "design":
            if len(parts) < 2:
                respond(
                    blocks=format_error(
                        "Missing sequence. Usage: `/crispr design <FASTA_sequence> [species]`"
                    ),
                    response_type="ephemeral",
                )
                return

            # Parse sequence and optional species
            remaining = parts[1] if len(parts) == 2 else parts[1] + " " + parts[2]

            # Check if last word is a species name
            tokens = remaining.rsplit(None, 1)
            if len(tokens) == 2 and tokens[1].lower() in SUPPORTED_SPECIES:
                sequence = tokens[0]
                species = tokens[1].lower()
            else:
                sequence = remaining
                species = "human"  # Default

            # Validate
            clean_seq = sequence.replace(">", "").replace("\n", "").strip()
            # Remove any FASTA header for length check
            seq_lines = sequence.strip().split("\n")
            pure_seq = "".join(
                line.strip() for line in seq_lines if not line.startswith(">")
            )
            if len(pure_seq) < 23 or len(pure_seq) > 1000:
                respond(
                    blocks=format_error(
                        f"Sequence length must be 23-1000 bp (got {len(pure_seq)} bp)."
                    ),
                    response_type="ephemeral",
                )
                return

            respond(
                text=f"🔄 Designing gRNAs for your {len(pure_seq)}bp sequence ({species})... this may take a moment.",
                response_type="in_channel",
            )

            result = idt.design_custom_grna(sequence, species)
            respond(
                blocks=format_custom_results(result, species),
                response_type="in_channel",
            )

        # ── /crispr check <20bp_sequence> [species] ──────────────────
        elif subcommand == "check":
            if len(parts) < 2:
                respond(
                    blocks=format_error(
                        "Missing sequence. Usage: `/crispr check <20bp_sequence> [species]`"
                    ),
                    response_type="ephemeral",
                )
                return

            # Parse 20bp sequence and optional species
            if len(parts) == 3 and parts[2].lower() in SUPPORTED_SPECIES:
                sequence = parts[1].strip().upper()
                species = parts[2].lower()
            elif len(parts) == 2:
                tokens = parts[1].rsplit(None, 1)
                if len(tokens) == 2 and tokens[1].lower() in SUPPORTED_SPECIES:
                    sequence = tokens[0].strip().upper()
                    species = tokens[1].lower()
                else:
                    sequence = parts[1].strip().upper()
                    species = "human"
            else:
                sequence = parts[1].strip().upper()
                species = "human"

            # Validate 20bp
            if len(sequence) != 20 or not all(c in "ACGT" for c in sequence):
                respond(
                    blocks=format_error(
                        f"Sequence must be exactly 20 bases (A/C/G/T only). Got {len(sequence)} chars."
                    ),
                    response_type="ephemeral",
                )
                return

            respond(
                text=f"🔄 Checking `{sequence}` against {species} genome...",
                response_type="in_channel",
            )

            result = idt.check_grna_sequence(sequence, species)
            respond(
                blocks=format_checker_results(result, sequence, species),
                response_type="in_channel",
            )

        # ── /crispr predesign <gene> [species] ───────────────────────
        elif subcommand == "predesign":
            if len(parts) < 2:
                respond(
                    blocks=format_error(
                        "Missing gene symbol. Usage: `/crispr predesign <gene_symbol> [species]`"
                    ),
                    response_type="ephemeral",
                )
                return

            gene = parts[1].strip().upper()
            species = parts[2].lower() if len(parts) == 3 and parts[2].lower() in SUPPORTED_SPECIES else "human"

            respond(
                text=f"🔄 Looking up predesigned gRNAs for *{gene}* ({species})...",
                response_type="in_channel",
            )

            result = idt.get_predesigned_grna(gene, species, num_results=5)
            respond(
                blocks=format_predesign_results(result, gene, species),
                response_type="in_channel",
            )

        else:
            respond(
                blocks=format_error(
                    f"Unknown subcommand `{subcommand}`. Use `/crispr help` for usage."
                ),
                response_type="ephemeral",
            )

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = ""
        try:
            body = e.response.json() if e.response is not None else ""
        except Exception:
            body = e.response.text[:200] if e.response is not None else str(e)
        logger.error("IDT API HTTP error %s: %s", status, body)
        respond(
            blocks=format_error(
                f"IDT API returned HTTP {status}. Check credentials and input format.\n`{body}`"
            ),
            response_type="ephemeral",
        )
    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach IDT API")
        respond(
            blocks=format_error("Cannot connect to IDT API. Check network/firewall."),
            response_type="ephemeral",
        )
    except Exception as e:
        logger.exception("Unexpected error handling /crispr command")
        respond(
            blocks=format_error(f"Unexpected error: {str(e)[:200]}"),
            response_type="ephemeral",
        )


# ── Optional: handle @bot mentions with natural language ──────────────────

@app.event("app_mention")
def handle_mention(event, say):
    """Respond to @bot mentions with help text."""
    say(
        blocks=format_help(),
        thread_ts=event.get("ts"),
    )


# ─── Main Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Validate required env vars
    missing = []
    for var in [
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "IDT_CLIENT_ID",
        "IDT_CLIENT_SECRET",
        "IDT_USERNAME",
        "IDT_PASSWORD",
    ]:
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        logger.error("Copy .env.example to .env and fill in your credentials.")
        exit(1)

    logger.info("Starting IDT CRISPR Slack bot (Socket Mode)...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
