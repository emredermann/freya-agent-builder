"""Builds standalone mock-worker/index.js and wrangler.toml from final_case."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FINAL_CASE = ROOT / "final_case"
DATA_FILE = FINAL_CASE / "test-environment" / "test-customers.json"
OUT_DIR = ROOT / "mock-worker"
OUT_DIR.mkdir(exist_ok=True)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    raw_data = json.load(f)

customers_map = {}
cards_map = {}

for c in raw_data["customers"]:
    cno = str(c["customerNo"])
    s = c["services"]
    customers_map[cno] = {
        "cards_list": s.get("cards.list"),
        "email_get": s.get("contact.email.get"),
        "pdf_send": s.get("statement.pdf.send"),
    }
    for card_no, val in s.get("cards.balance", {}).items():
        cards_map.setdefault(card_no, {})["balance"] = val
        cards_map[card_no]["customerNo"] = cno
    for card_no, val in s.get("statement.week.get", {}).items():
        cards_map.setdefault(card_no, {})["week_get"] = val
    for card_no, val in s.get("statement.week.decide", {}).items():
        cards_map.setdefault(card_no, {})["week_decide"] = val
    for card_no, val in s.get("statement.week.change", {}).items():
        cards_map.setdefault(card_no, {})["week_change"] = val

db_json = json.dumps({"customers": customers_map, "cards": cards_map}, ensure_ascii=False)

worker_code = f"""// Standalone Cloudflare Worker for Freya Bank Statement Debt Mock API
// Auto-generated from service-contract.md and test-customers.json

const DB = {db_json};
const CUSTOMERS = DB.customers;
const CARDS = DB.cards;

const DEFAULT_CUSTOMER = "90000001";
const DEFAULT_CARD = "540000******1234";

const CORS_HEADERS = {{
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, X-Requested-With",
  "Access-Control-Max-Age": "86400",
}};

function jsonResponse(body, status = 200) {{
  return new Response(JSON.stringify(body), {{
    status: status,
    headers: {{
      ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
    }},
  }});
}}

function isTemplateVar(val) {{
  if (typeof val !== "string") return false;
  const s = val.trim();
  return s.startsWith("{{{{") || s.startsWith("%7B%7B") || s.includes("{{{{") || s === "";
}}

async function readPayload(request) {{
  try {{
    const ct = request.headers.get("content-type") || "";
    if (ct.includes("application/json")) {{
      const b = await request.json();
      return b?.data || b || {{}};
    }}
    if (ct.includes("application/x-www-form-urlencoded")) {{
      const text = await request.text();
      const params = new URLSearchParams(text);
      const obj = {{}};
      for (const [k, v] of params.entries()) obj[k] = v;
      return obj;
    }}
    const raw = await request.text();
    if (!raw) return {{}};
    return JSON.parse(raw);
  }} catch {{
    return {{}};
  }}
}}

// Standard error responses from Section 4 of 2026-10-01-service-contract.md
function errCardsList404() {{
  return jsonResponse({{
    result: {{
      guid: "f0e1d2c3b4a5968778695a4b3c2d0001",
      returnCode: "FB_IVR_CHANNEL_102",
      messageText: "Müşteriye ait geçerli kart bilgisi bulunamadı.",
      code: "FB_IVR_CHANNEL_102",
      message: "Müşteriye ait geçerli kart bilgisi bulunamadı.",
      type: "WARNING",
      details: {{
        guid: "f0e1d2c3b4a5968778695a4b3c2d0001",
        rootCause: "NotFoundException",
        errorOrigin: "ivr-gateway-test:ivr-channel-v0",
      }},
    }},
  }}, 404);
}}

function errCardBalance404() {{
  return jsonResponse({{
    result: {{
      guid: "f0e1d2c3b4a5968778695a4b3c2d0002",
      returnCode: "FB_IVR_CHANNEL_120",
      messageText: "Kart bakiye servisi hatası: kart bulunamadı",
      code: "FB_IVR_CHANNEL_120",
      message: "Kart bakiye servisi hatası: kart bulunamadı",
      type: "WARNING",
      details: {{
        guid: "f0e1d2c3b4a5968778695a4b3c2d0002",
        rootCause: "NotFoundException",
        errorOrigin: "ivr-gateway-test:ivr-channel-v0",
      }},
    }},
  }}, 404);
}}

function errWeekGet404() {{
  return jsonResponse({{
    result: {{
      guid: "f0e1d2c3b4a5968778695a4b3c2d0003",
      returnCode: "FB_IVR_CHANNEL_121",
      messageText: "Hesap kesim haftası bulunamadı",
      code: "FB_IVR_CHANNEL_121",
      message: "Hesap kesim haftası bulunamadı",
      type: "WARNING",
      details: {{
        guid: "f0e1d2c3b4a5968778695a4b3c2d0003",
        rootCause: "NotFoundException",
        errorOrigin: "ivr-gateway-test:ivr-channel-v0",
      }},
    }},
  }}, 404);
}}

function errPdfSend404() {{
  return jsonResponse({{
    result: {{
      guid: "f0e1d2c3b4a5968778695a4b3c2d0466",
      returnCode: "FB_IVR_CHANNEL_107",
      messageText: "Pdf dokümanı bulunamadı",
      code: "FB_IVR_CHANNEL_107",
      message: "Pdf dokümanı bulunamadı",
      type: "WARNING",
      details: {{
        guid: "f0e1d2c3b4a5968778695a4b3c2d0466",
        rootCause: "com.freyabank.ivrgateway.ivrchannel.rest.exception.NotFoundException",
        errorOrigin: "ivr-gateway-test:ivr-channel-v0",
      }},
    }},
  }}, 404);
}}

function errInvalidArgs(msg = "Geçersiz parametre") {{
  return jsonResponse({{
    result: {{
      guid: "f0e1d2c3b4a5968778695a4b3c2d0005",
      returnCode: "INVALID_ARGUMENTS_ERROR",
      messageText: msg,
      code: "INVALID_ARGUMENTS_ERROR",
      message: msg,
      type: "ERROR",
      details: {{
        guid: "f0e1d2c3b4a5968778695a4b3c2d0005",
        rootCause: "IllegalArgumentException",
        errorOrigin: "ivr-gateway-test:ivr-channel-v0",
      }},
    }},
  }}, 400);
}}

function sleep(ms) {{
  return new Promise((resolve) => setTimeout(resolve, ms));
}}

export default {{
  async fetch(request) {{
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\\/voice\\/v1/, "");

    // 1. CORS Preflight
    if (request.method === "OPTIONS") {{
      return new Response(null, {{ headers: CORS_HEADERS }});
    }}

    // 2. Health & Diagnostic
    if (request.method === "GET") {{
      if (path === "" || path === "/" || path === "/health") {{
        return jsonResponse({{
          service: "Freya Bank Statement Debt Mock API",
          durum: "ok",
          status: "online",
          version: "1.0.0",
          endpoints: [
            "POST /voice/v1/cards.list",
            "POST /voice/v1/cards.balance",
            "POST /voice/v1/statement.week.get",
            "POST /voice/v1/statement.week.decide",
            "POST /voice/v1/statement.week.change",
            "POST /voice/v1/contact.email.get",
            "POST /voice/v1/statement.pdf.send",
            "POST /oauth2/token",
          ],
        }});
      }}
    }}

    // 3. OAuth2 Token
    if (path === "/oauth2/token" || url.pathname === "/oauth2/token") {{
      return jsonResponse({{
        access_token: "mock_token_voice_statement_2026",
        token_type: "Bearer",
        expires_in: 1800,
      }});
    }}

    // Only POST is accepted for service endpoints
    if (request.method !== "POST") {{
      return jsonResponse({{ error: "Method not allowed" }}, 405);
    }}

    const payload = await readPayload(request);

    // Endpoint: cards.list
    if (path === "/cards.list") {{
      let cno = payload.customerNo || payload.customerNumber;
      if (isTemplateVar(cno)) cno = DEFAULT_CUSTOMER;
      cno = String(cno || "").trim();

      const cust = CUSTOMERS[cno];
      if (!cust || !cust.cards_list) {{
        return errCardsList404();
      }}
      return jsonResponse(cust.cards_list.response, cust.cards_list.http || 200);
    }}

    // Endpoint: cards.balance
    if (path === "/cards.balance") {{
      let card = payload.cardNumber;
      if (isTemplateVar(card)) card = DEFAULT_CARD;
      card = String(card || "").trim();

      const cData = CARDS[card];
      if (!cData || !cData.balance) {{
        return errCardBalance404();
      }}
      const bal = cData.balance;
      if (bal.delaySeconds && bal.delaySeconds > 0) {{
        await sleep(bal.delaySeconds * 1000);
      }}
      return jsonResponse(bal.response, bal.http || 200);
    }}

    // Endpoint: statement.week.get
    if (path === "/statement.week.get") {{
      let card = payload.cardNumber;
      if (isTemplateVar(card)) card = DEFAULT_CARD;
      card = String(card || "").trim();

      const cData = CARDS[card];
      if (!cData || !cData.week_get) {{
        return errWeekGet404();
      }}
      return jsonResponse(cData.week_get.response, cData.week_get.http || 200);
    }}

    // Endpoint: statement.week.decide
    if (path === "/statement.week.decide") {{
      let card = payload.cardNumber;
      let week = payload.newStatementWeek;
      if (isTemplateVar(card)) card = DEFAULT_CARD;
      if (isTemplateVar(week)) week = "2";
      card = String(card || "").trim();
      week = String(week || "").trim();

      const cData = CARDS[card];
      if (!cData || !cData.week_decide || !cData.week_decide[week]) {{
        return errInvalidArgs("Hafta önizlemesi bulunamadı veya geçersiz hafta");
      }}
      const dec = cData.week_decide[week];
      return jsonResponse(dec.response, dec.http || 200);
    }}

    // Endpoint: statement.week.change
    if (path === "/statement.week.change") {{
      let card = payload.cardNumber;
      let week = payload.newStatementWeek;
      if (isTemplateVar(card)) card = DEFAULT_CARD;
      if (isTemplateVar(week)) week = "2";
      card = String(card || "").trim();
      week = String(week || "").trim();

      const cData = CARDS[card];
      if (!cData || !cData.week_change || !cData.week_change[week]) {{
        return errInvalidArgs("Hesap kesim haftası değiştirilemedi veya geçersiz parametre");
      }}
      const chg = cData.week_change[week];
      return jsonResponse(chg.response, chg.http || 200);
    }}

    // Endpoint: contact.email.get
    if (path === "/contact.email.get") {{
      let cno = payload.customerNo || payload.customerNumber;
      if (isTemplateVar(cno)) cno = DEFAULT_CUSTOMER;
      cno = String(cno || "").trim();

      const cust = CUSTOMERS[cno];
      if (!cust || !cust.email_get) {{
        return errInvalidArgs("Müşteri iletişim bilgisi bulunamadı");
      }}
      return jsonResponse(cust.email_get.response, cust.email_get.http || 200);
    }}

    // Endpoint: statement.pdf.send
    if (path === "/statement.pdf.send") {{
      let cno = payload.customerNo || payload.customerNumber;
      let card = payload.cardNumber;
      if (isTemplateVar(cno) && isTemplateVar(card)) {{
        cno = DEFAULT_CUSTOMER;
        card = DEFAULT_CARD;
      }}
      cno = String(cno || "").trim();
      card = String(card || "").trim();

      let cust = CUSTOMERS[cno];
      if (!cust && card && CARDS[card]) {{
        cno = CARDS[card].customerNo;
        cust = CUSTOMERS[cno];
      }}

      if (!cust || !cust.pdf_send) {{
        return errPdfSend404();
      }}
      return jsonResponse(cust.pdf_send.response, cust.pdf_send.http || 200);
    }}

    return jsonResponse({{ error: "Not found", path: url.pathname }}, 404);
  }},
}};
"""

out_index = OUT_DIR / "index.js"
out_index.write_text(worker_code, encoding="utf-8")
print(f"Generated {out_index} ({round(len(worker_code)/1024, 1)} KB)")

wrangler_toml = """name = "freya-bank-mock"
main = "index.js"
compatibility_date = "2025-01-01"

[observability]
enabled = true
"""

out_toml = OUT_DIR / "wrangler.toml"
out_toml.write_text(wrangler_toml, encoding="utf-8")
print(f"Generated {out_toml}")
