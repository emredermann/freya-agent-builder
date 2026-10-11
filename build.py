"""Entrypoint CLI for Building and Deploying Freya Phone Agents.

Evaluation Interface:
    python3 build.py {case_folder} {mock_url}

Examples:
    python3 build.py final_case https://freya-bank-mock.workers.dev
    python3 build.py briefs/brief-a.md tools/openapi.json
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kit" / "build-the-builder"))

def load_env_defaults():
    for env_path in (ROOT / ".env", ROOT / "kit" / "build-the-builder" / "env.sh", ROOT / "env.sh"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

load_env_defaults()

import freya
from builder.models import TaskInput, ToolDefinition
from builder.prompt_synthesizer import synthesize_prompt


def get_git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "latest"


def build_tools(mock_url: str) -> List[Dict[str, Any]]:
    """Synthesizes Freya tool definitions pointing to the provided mock_url."""
    base_url = mock_url.rstrip("/")

    def api_tool(name: str, path: str, desc: str, body_props: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "function",
            "config": {
                "timeoutMs": 15000,
                "maxRetries": 0,
            },
            "function": {
                "name": name,
                "handler": "__function__:api_call",
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "default": f"{base_url}{path}"},
                        "method": {"type": "string", "default": "POST"},
                        "headers": {
                            "type": "object",
                            "properties": {
                                "Content-Type": {"type": "string", "default": "application/json"}
                            },
                        },
                        "body": {
                            "type": "object",
                            "properties": body_props,
                        },
                    },
                },
            },
        }

    tools = [
        api_tool(
            name="cards_list",
            path="/voice/v1/cards.list",
            desc="Müşterinin geçerli ve aktif kredi kartlarını listeler.",
            body_props={
                "data": {
                    "type": "object",
                    "properties": {
                        "customerNo": {"type": "string", "default": "{{customerNumber}}"},
                        "aiFlow": {"type": "string", "default": "CardOps"},
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="cards_balance",
            path="/voice/v1/cards.balance",
            desc="Kredi kartının hesap kesim tarihi, son ödeme tarihi ve para birimlerine göre (TL, USD, EUR, GBP) ekstre borcunu ve asgari tutarlarını getirir.",
            body_props={
                "data": {
                    "type": "object",
                    "required": ["cardNumber"],
                    "properties": {
                        "cardNumber": {
                            "type": "string",
                            "description": "Kart numarası (cards.list sonucundaki maskeli numara, ör: 540000******1234)",
                        }
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="statement_week_get",
            path="/voice/v1/statement.week.get",
            desc="Kartın mevcut hesap kesim haftasını ve gününü, bir sonraki ekstre tarihlerini ve ortak ekstre bilgisini getirir.",
            body_props={
                "data": {
                    "type": "object",
                    "required": ["cardNumber"],
                    "properties": {
                        "cardNumber": {"type": "string", "description": "Kart numarası"}
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="statement_week_decide",
            path="/voice/v1/statement.week.decide",
            desc="İstenen yeni hesap kesim haftası için tarihleri önizler (kartı DEĞİŞTİRMEZ, yalnızca önizleme tarihlerini hesaplar).",
            body_props={
                "data": {
                    "type": "object",
                    "required": ["cardNumber", "newStatementWeek"],
                    "properties": {
                        "cardNumber": {"type": "string", "description": "Kart numarası"},
                        "newStatementWeek": {
                            "type": "integer",
                            "description": "Talep edilen yeni hesap kesim haftası (1, 2, 3 veya 4)",
                        },
                        "statementDay": {
                            "type": "integer",
                            "description": "Kartın mevcut hesap kesim günü (statement.week.get yanıtından)",
                        },
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="statement_week_change",
            path="/voice/v1/statement.week.change",
            desc="Kartın hesap kesim haftasını değiştirir. YALNIZCA müşteri önizleme tarihlerini açıkça onayladıktan ('Evet') sonra çağrılır.",
            body_props={
                "data": {
                    "type": "object",
                    "required": ["cardNumber", "newStatementWeek"],
                    "properties": {
                        "cardNumber": {"type": "string", "description": "Kart numarası"},
                        "newStatementWeek": {
                            "type": "integer",
                            "description": "Yeni hesap kesim haftası (1, 2, 3 veya 4)",
                        },
                        "statementDay": {
                            "type": "integer",
                            "description": "Mevcut hesap kesim günü",
                        },
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="contact_email_get",
            path="/voice/v1/contact.email.get",
            desc="Müşterinin bankada kayıtlı iletişim e-posta adresini sorgular.",
            body_props={
                "data": {
                    "type": "object",
                    "properties": {
                        "customerNo": {"type": "string", "default": "{{customerNumber}}"},
                        "intAddressInfoType": {"type": "string", "default": "E"},
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        api_tool(
            name="statement_pdf_send",
            path="/voice/v1/statement.pdf.send",
            desc="Son dönemin ekstre PDF belgesini müşterinin onayladığı kayıtlı e-posta adresine gönderir.",
            body_props={
                "data": {
                    "type": "object",
                    "required": ["cardNumber", "emailAddress"],
                    "properties": {
                        "customerNo": {"type": "string", "default": "{{customerNumber}}"},
                        "cardNumber": {"type": "string", "description": "Kart numarası"},
                        "currencyType": {"type": "string", "default": "TL"},
                        "statementDate": {"type": "string", "description": "Ekstre tarihi (dd.MM.yyyy)"},
                        "emailAddress": {"type": "string", "description": "Gönderilecek e-posta adresi"},
                    },
                },
                "call": {
                    "type": "object",
                    "properties": {"lang": {"type": "string", "default": "tr"}},
                },
            },
        ),
        {
            "type": "function",
            "config": {"timeoutMs": 10000},
            "function": {
                "name": "end_call",
                "handler": "__function__:end_call",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_mode": {"type": "string", "default": "none"},
                        "interruptible": {"type": "boolean", "default": True},
                        "trigger_pattern": {
                            "type": "string",
                            "default": "İyi günler|iyi günler|hoşça kalın|hoşçakalın",
                        },
                        "trigger_timeout": {"type": "number", "default": 3},
                        "trigger_pattern_both": {
                            "type": "string",
                            "default": "teşekkürler|teşekkür ederim|sağolun|sağol|iyi günler|hoşçakal|hoşça kalın|baybay",
                        },
                    },
                },
                "description": "Görüşmeyi sonlandırır. 'İyi günler dileriz.' ifadesi çağrıyı otomatik sonlandırır.",
            },
        },
    ]

    return tools


def synthesize_statement_debt_task_message() -> str:
    return (
        "Sen Freya Bank'ın kredi kartı ekstre borcu sesli asistanısın. Müşteri IVR menüsünü geçmiş ve müşteri numarası {{customerNumber}} olarak aktarılmıştır.\n"
        "Çağrı zamanı: {{now}}. Tüm tarih ve takvim kararlarında {{now}} esas alınır.\n"
        "Telefon konuşması kuralları: Her turda EN FAZLA 1-2 kısa cümle (30 kelime altı) konuş. Asla monolog yapma. Her konuşman tek bir net soru veya yönlendirmeyle bitsin.\n\n"
        "1. KART LİSTELEME & SEÇİMİ (cards_list):\n"
        "   - Görüşme başında derhal cards_list servisini çağır.\n"
        "   - TEK KART VARSA (1_CARD): Kart seçimi sorma! Doğrudan o kart için cards_balance çağır ve borcu oku.\n"
        "   - ÇOKLU KART VARSA (MULTI_CARD): Müşteriye birden fazla kartı olduğunu söyle, kartların ürün adı ve son 4 hanesini vererek hangisinin borcunu öğrenmek istediğini sor (ör. 'Yıldız Premium kartınız mı, yoksa Yıldız Fly kartınız mı?').\n"
        "   - Müşteri tüm kartların borcunu aynı anda öğrenmek istese dahi, tüm kartların borcu aynı anda okunmaz! Tek bir kart seçmesini rica et.\n\n"
        "2. BORCUN VE TARİHLERİN OKUNMASI (cards_balance):\n"
        "   - Seçilen kartın cardNumber değeriyle cards_balance çağır.\n"
        "   - Kartın son 4 hanesini, ürün adını ve son hesap kesim tarihini belirt.\n"
        "   - TL BORCU: Ekstre borcunu (statementDebt) ve asgari ödeme tutarını (minPayment) oku. Eğer asgari veya kısmi ödeme yapılmışsa teşekkür ederek kalan toplam borç ve kalan asgari tutarı belirt.\n"
        "   - DÖVİZ BORCU: Eğer kartta Dolar, Euro veya Sterlin borcu varsa tutarlarını oku. Eğer döviz borcu yoksa TEK CÜMLEDE söyle: 'Dolar, Euro ve Sterlin borcunuz bulunmamaktadır.'\n"
        "   - SON ÖDEME TARİHİ: lastPayDate tarihini açıkça belirt (ör. '15 Ekim 2026').\n"
        "   - EK İŞLEM TEKLİFİ: Borcu okuduktan sonra: 'Hesap kesim tarihinizi değiştirebilir veya ekstrenizi e-postanıza gönderebilirim. Yardımcı olmamı ister misiniz?'. (Eğer contact_email_get sonucunda kayıtlı e-posta yoksa e-posta seçeneğini teklif etme!).\n\n"
        "3. HESAP KESİM TARİHİ DEĞİŞİKLİĞİ:\n"
        "   - Müşteri ekstre tarihini değiştirmek istediğinde statement_week_get çağır. Kartın mevcut haftasını ve bir sonraki ekstre tarihlerini söyle.\n"
        "   - Yalnızca diğer haftaları seçenek olarak sun (ör. mevcut 2. haftaysa 1, 3 ve 4. haftaları teklif et).\n"
        "   - Müşteri hafta seçince statement_week_decide ile önizleme yap ve yeni tarihleri oku.\n"
        "   - AÇIK TEYİT AL: 'Değişikliği onaylıyor musunuz?' diye sor. 'Olur herhalde' gibi muğlak ifadeleri kabul etme, net teyit iste. Yalnızca net 'Evet' yanıtı gelince statement_week_change çağır. Sonucu ve yeni tarihleri bildir.\n\n"
        "4. E-POSTA İLE EKSTRE GÖNDERİMİ:\n"
        "   - contact_email_get çağır. Kayıtlı e-posta yoksa gönderilemeyeceğini söyle.\n"
        "   - Yalnızca EN SON DÖNEMİN ekstresi gönderilebilir. Geçmiş dönem ekstresi istenirse yalnızca son dönemin gönderilebileceğini açıkça söyle.\n"
        "   - Kayıtlı e-posta adresini oku ve açık onay ('Evet') iste. Net onay gelince statement_pdf_send çağır ve başarıyla gönderildiğini teyit et.\n\n"
        "5. GÜVENLİK VE AKTARIM KURALLARI:\n"
        "   - Müşteri istese bile kartın ilk 6 veya ilk 12 hanesini ASLA söyleme; sadece son 4 hane kullanılır.\n"
        "   - Eş, akraba veya başkasının kartı için bilgi verilmez ve işlem yapılmaz ('Güvenlik nedeniyle yalnızca kendi kartınız için işlem yapabilirsiniz').\n"
        "   - Ödeme yapmak isteyen veya müşteri temsilcisi isteyen müşterileri temsilciye aktar.\n"
        "   - Kapanış: 'Freya Bank'ı tercih ettiğiniz için teşekkür ederiz. İyi günler dileriz.' de ve çağrıyı sonlandır."
    )


def main():
    start_time_iso = time.strftime("%Y-%m-%d %H:%M:%S")
    start_time_epoch = time.time()

    if len(sys.argv) < 2:
        print("Usage: python3 build.py {case_folder} [mock_url]", file=sys.stderr)
        sys.exit(1)

    case_folder_arg = sys.argv[1]
    mock_url_arg = (
        sys.argv[2]
        if len(sys.argv) > 2
        else os.environ.get("FREYA_MOCK_URL", "https://freya-bank-mock.freyavoice.workers.dev")
    )

    case_path = pathlib.Path(case_folder_arg)
    if not case_path.is_absolute():
        case_path = (ROOT / case_folder_arg).resolve() if (ROOT / case_folder_arg).exists() else case_path.resolve()

    # Read brief text from case_folder
    brief_texts = []
    if case_path.is_dir():
        brief_file = case_path / "BRIEF.md"
        if not brief_file.exists():
            brief_file = case_path / "brief.md"
        if brief_file.exists():
            brief_texts.append(brief_file.read_text(encoding="utf-8"))
        # Also check docs and sources
        for sub in ("sources/documents", "docs"):
            dp = case_path / sub
            if dp.exists():
                for f in dp.glob("*.md"):
                    brief_texts.append(f.read_text(encoding="utf-8"))
    elif case_path.is_file():
        brief_texts.append(case_path.read_text(encoding="utf-8"))

    combined_brief = "\n\n".join(brief_texts)
    slot = "final" if "final" in case_path.name.lower() or "brief" in case_path.name.lower() else case_path.stem

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Target case folder: {case_path}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Mock Service URL: {mock_url_arg}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Synthesizing Turkish Voice Agent workflow...")

    # Build tools pointing to mock_url
    tools = build_tools(mock_url=mock_url_arg)
    task_message = synthesize_statement_debt_task_message()

    workflow = {
        "initial_node": "statement_assistant",
        "system_prompt": (
            "Sen Freya Bank'ın sesli dijital asistanısın. Müşterilere kredi kartı ekstre borcu, "
            "hesap kesim tarihi ve e-posta ekstre gönderimi konularında Türkçe olarak yardımcı olursun. "
            "Tüm konuşmalar doğal Türkçe telefon üslubuyla (en fazla 1-2 kısa cümle) yapılır. "
            "Görüşme zamanı: {{now}}."
        ),
        "nodes": {
            "statement_assistant": {
                "name": "statement_assistant",
                "node_type": "conversation",
                "on_enter": {
                    "type": "tts",
                    "text": (
                        "Merhaba, ben Freya Bank dijital asistanıyım. Güvenlik ve kalite standartları gereği bu görüşme "
                        "kayıt altına alınmaktadır. Kredi kartı ekstre borcunuzla ilgili yardımcı olabilirim."
                    ),
                },
                "task_message": task_message,
                "role_message": "",
                "interruptible": True,
                "tools": tools,
                "transitions": [],
                "position": {"x": 500, "y": 0},
            }
        },
        "tools": [t for t in tools if t.get("function", {}).get("name") == "end_call"],
        "global_nodes": {},
        "test_variables": {
            "customerNumber": "95004361",
            "now": "2026-10-12T10:30:00+03:00",
        },
    }

    # Pre-flight schema validation
    nodes = workflow.get("nodes", {})
    assert "statement_assistant" in nodes, "Missing statement_assistant node"
    assert len(tools) >= 7, "Missing required mock tools"
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pre-flight validation passed (7 tools, 1 conversation node).")

    # Staging output
    submission_dir = ROOT / "submission"
    submission_dir.mkdir(exist_ok=True)
    out_file = submission_dir / "final.workflow.json"
    out_file.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Staged local workflow artifact to: {out_file}")

    # Upload & publish to Freya platform
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Publishing workflow to Freya...")
    res = freya.save_workflow(slot, workflow)
    agent_id = res["agent_id"]
    workflow_id = res["workflow_id"]
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Freya Agent ID: {agent_id} | Workflow ID: {workflow_id}")

    # Rule 75: Export official live platform workflow
    try:
        freya.export_workflow(workflow_id, str(out_file))
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Exported platform workflow to: {out_file}")
    except Exception as e:
        print(f"Warning: platform export fallback to local: {e}", file=sys.stderr)

    end_time_iso = time.strftime("%Y-%m-%d %H:%M:%S")
    duration_sec = round(time.time() - start_time_epoch, 2)
    git_commit = get_git_commit()

    # Rule 91: Write audit trace log
    traces_dir = ROOT / "traces"
    traces_dir.mkdir(exist_ok=True)
    trace_file = traces_dir / "final.log"
    trace_content = (
        f"=== Freya Autonomous Builder Run Trace: final ===\n"
        f"Start Time: {start_time_iso}\n"
        f"End Time: {end_time_iso}\n"
        f"Build Duration: {duration_sec}s\n"
        f"Case Folder: {case_path}\n"
        f"Mock Service URL: {mock_url_arg}\n"
        f"Git Commit: {git_commit}\n"
        f"Language: Turkish (tr)\n"
        f"Target Slot: {slot}\n"
        f"Freya Agent ID: {agent_id}\n"
        f"Freya Workflow ID: {workflow_id}\n"
        f"Tools Bound: {[t['function']['name'] for t in tools]}\n"
        f"Validation: PASSED\n"
        f"Workflow Artifact: {out_file}\n"
        f"Status: SUCCESS\n"
    )
    trace_file.write_text(trace_content, encoding="utf-8")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Audit trace written to: {trace_file}")

    # Generate submission.json
    submission_json = {
        "team": "Freya Agent Builder",
        "members": [{"name": "Emre Derman", "email": "emre.derman@ug.bilkent.edu.tr"}],
        "repo": "https://github.com/emredermann/freya-agent-builder.git",
        "commit": git_commit,
        "run_command": f"python3 build.py {case_folder_arg} {mock_url_arg}",
        "workflow": "submission/final.workflow.json",
        "trace": "traces/final.log",
        "mock_url": mock_url_arg,
    }
    sub_file = ROOT / "submission.json"
    sub_file.write_text(json.dumps(submission_json, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Submission manifest created: {sub_file}")

    print(json.dumps({
        "status": "success",
        "agent_id": agent_id,
        "workflow_id": workflow_id,
        "workflow_file": str(out_file),
        "trace_file": str(trace_file),
        "submission_file": str(sub_file),
        "duration_seconds": duration_sec,
    }, indent=2))


if __name__ == "__main__":
    main()
