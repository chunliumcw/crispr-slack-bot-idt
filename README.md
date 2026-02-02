[README.md](https://github.com/user-attachments/files/25000664/README.md)
# 🧬 IDT CRISPR gRNA Design Bot for Slack

A Python Slack bot that integrates **IDT SciTools Plus API** to design, check, and look up CRISPR-Cas9 guide RNAs directly from Slack slash commands.

---

## What It Does

| Command | Description | IDT Tool |
|---------|-------------|----------|
| `/crispr design <FASTA> [species]` | Design custom gRNAs from a target sequence (23-1000 bp) | CRISPR_CUSTOM |
| `/crispr check <20bp> [species]` | Check a 20bp protospacer for on/off-target scores | CRISPR_SEQUENCE |
| `/crispr predesign <gene> [species]` | Look up predesigned gRNAs by gene symbol | CRISPR_PREDESIGN |
| `/crispr help` | Show usage information | — |

**Supported species:** human, mouse, rat, zebrafish, celegans

---

## Setup (4 Steps)

### Step 1: Get IDT API Credentials

1. Log into [idtdna.com](https://www.idtdna.com)
2. Click your username (top right) → **My Account**
3. Click **API Access**
4. Click **Request new API key**
5. Enter a Client ID name (e.g., `slack-crispr-bot`) and description
6. Save the **Client ID** and **Client Secret** — you will need both

> IDT allows 500 API calls/minute. The API is free for account holders.

### Step 2: Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g., `CRISPR gRNA Bot`) and select your workspace

**Enable Socket Mode:**
- **Settings → Socket Mode** → Toggle ON
- It will prompt you to create an App-Level Token — name it `socket` and add the `connections:write` scope
- Copy the `xapp-...` token

**Add Bot Permissions:**
- **OAuth & Permissions → Bot Token Scopes** → Add:
  - `chat:write`
  - `commands`
  - `app_mentions:read`

**Create Slash Command:**
- **Slash Commands → Create New Command**
  - Command: `/crispr`
  - Short description: `Design & check CRISPR gRNAs via IDT`
  - Usage hint: `design|check|predesign <input> [species]`

**Install to Workspace:**
- **Install App** → Install to your workspace
- Copy the **Bot User OAuth Token** (`xoxb-...`)

**Enable Events (optional, for @mentions):**
- **Event Subscriptions** → Toggle ON
- Subscribe to `app_mention` under Bot Events

### Step 3: Configure Environment

```bash
cd idt-slack-bot
cp .env.example .env
```

Edit `.env` with your actual credentials:

```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
IDT_CLIENT_ID=your-idt-client-id
IDT_CLIENT_SECRET=your-idt-client-secret
IDT_USERNAME=your-idt-email@example.com
IDT_PASSWORD=your-idt-password
```

### Step 4: Run the Bot

**Option A — Direct (Python):**
```bash
pip install -r requirements.txt
# Load .env manually or use:
export $(grep -v '^#' .env | xargs)
python bot.py
```

**Option B — Docker:**
```bash
docker build -t idt-crispr-bot .
docker run -d --name crispr-bot --env-file .env idt-crispr-bot
```

**Option C — systemd service (Linux server):**
```bash
# See idt-crispr-bot.service for a ready-made unit file
sudo cp idt-crispr-bot.service /etc/systemd/system/
sudo systemctl enable --now idt-crispr-bot
```

---

## Usage Examples

### Design custom gRNAs for a target region
```
/crispr design ATGGCAGATTCCCAGTTGGACTGGTGGACCACAGCCAGGTCCTCCTGTCTGCAGAGTG human
```
Returns ranked gRNA candidates with IDT's ML-based on-target/off-target scores.

### Check a known 20bp guide sequence
```
/crispr check ATGGCAGATTCCCAGTTGGA human
```
Returns on-target and off-target scores for a specific 20bp protospacer.

### Look up predesigned gRNAs for a gene
```
/crispr predesign TNNT2 human
/crispr predesign MYH7 mouse
/crispr predesign BRCA1 human
```
Returns IDT's curated, pre-scored guide RNAs for a gene of interest.

---

## Architecture

```
Slack workspace
    │
    ▼
/crispr slash command
    │
    ▼
bot.py (Python, Slack Bolt — Socket Mode)
    │
    ├── IDT OAuth token endpoint
    │     POST https://www.idtdna.com/Identityserver/connect/token
    │
    ├── IDT CRISPR Custom Design
    │     POST /restapi/v1/CRISPR/Design/CRISPRCustom
    │
    ├── IDT CRISPR Sequence Checker
    │     POST /restapi/v1/CRISPR/Design/CRISPRSequenceChecker
    │
    └── IDT CRISPR Predesigned Lookup
          POST /restapi/v1/CRISPR/Design/CRISPRPredesign
    │
    ▼
Formatted results posted to Slack channel
```

**Socket Mode** means no public URL/server needed — the bot connects outbound to Slack via WebSocket. Runs behind firewalls, on a lab Mac/Linux machine, or in Docker.

---

## IDT Scoring Details

IDT's on-target model was built using machine learning trained on **>1400 features** across **560 guide sequences**. Features include:
- Base composition and position across the 20nt guide
- Self-hybridization probability (crRNA:tracrRNA)
- Predicted Cas9 editing efficiency

**Score interpretation (1-100):**
- 🟢 ≥60: High confidence — predicted >40% editing efficiency
- 🟡 40-59: Moderate — likely functional, consider testing alternatives
- 🔴 <40: Low — consider redesigning

Off-target analysis is available for: human, mouse, rat, zebrafish, C. elegans.

---

## API Endpoint Details

The Swagger documentation is available after authentication at IDT's API portal. Key CRISPR endpoints under `https://www.idtdna.com/restapi/v1/`:

| Endpoint | Method | Input | Output |
|----------|--------|-------|--------|
| `/CRISPR/Design/CRISPRCustom` | POST | FASTA (23-1000bp), species | Ranked gRNAs with scores |
| `/CRISPR/Design/CRISPRSequenceChecker` | POST | 20bp sequence, species | On/off-target scores |
| `/CRISPR/Design/CRISPRPredesign` | POST | Gene symbol, species | Curated gRNA library |

> **Note:** The exact endpoint paths shown are based on IDT's Swagger/Postman documentation patterns. If any path returns 404, check the Swagger UI at `https://www.idtdna.com/restapi/swagger` after authenticating, or import IDT's Postman collection to see the current endpoints.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `401 Unauthorized` from IDT | Check Client ID/Secret and IDT account credentials in `.env` |
| `404 Not Found` on CRISPR endpoint | Endpoint path may have changed — check IDT Swagger docs |
| Bot doesn't respond in Slack | Verify Socket Mode is ON and `SLACK_APP_TOKEN` is correct |
| `channel_not_found` | Invite the bot to the channel: `/invite @CRISPR gRNA Bot` |
| Rate limit (429) | IDT allows 500 calls/min — unlikely in normal use |
| Sequence validation error | Custom design: 23-1000bp FASTA; Checker: exactly 20bp A/C/G/T |

---

## File Structure

```
idt-slack-bot/
├── bot.py              # Main application
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── Dockerfile          # Container deployment
├── idt-crispr-bot.service  # systemd unit file (Linux)
└── README.md           # This file
```
