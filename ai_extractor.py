"""
NOTE: এই AI-based extractor এখনো app.py-তে wire করা হয়নি (Upcoming Update)।
রুল-বেজ সিস্টেম সম্পূর্ণ ক্লিয়ার হওয়ার পর এটা যোগ হবে।
Free করতে চাইলে Google Gemini API (gemini-2.5-flash) দিয়েও এটা বানানো
সম্ভব — Anthropic-এর বদলে শুধু endpoint/payload বদলাতে হবে।
"""
import os
import json
import base64
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"

EXTRACTION_PROMPT = """তুমি একজন গার্মেন্টস/কার্টন Purchase Order (PO) ডকুমেন্ট পড়ার এক্সপার্ট।
এই PDF-টা একটা কার্টন/প্যাকেজিং PO। এতে সাধারণত একটা বিস্তারিত লাইন-আইটেম টেবিল থাকে
(EWO No, Style No, PO No, Measurement, Ply, Quantity ইত্যাদি কলাম নিয়ে) যেটা একাধিক পেজ জুড়ে থাকতে পারে।

তোমার কাজ: এই PDF-এর সব লাইন-আইটেম বের করে নিচের exact JSON schema-তে ফেরত দাও।
কলামের নাম বিভিন্ন buyer-এ বিভিন্ন রকম হতে পারে (যেমন "EWO", "Ref No", "Booking No" ইত্যাদি
আসলে EWO No-ই বোঝাতে পারে) — অর্থ বুঝে সঠিক ফিল্ডে বসাও।

প্রতিটা লাইন-আইটেমের জন্য এই ফিল্ডগুলো দাও:
- item_name: কার্টনের ধরন/নেচার (যেমন "Master Carton", "Top Bottom", "Both Side Hanger Carton")। না পেলে "N/A"
- po_no: PO নম্বর (MUST HAVE - না পেলে "" খালি রাখো, অনুমান কোরো না)
- ewo_no: EWO নম্বর (MUST HAVE - না পেলে "" খালি রাখো)
- style_no: স্টাইল নম্বর/নাম (MUST HAVE - না পেলে "" খালি রাখো)
- length, width, height: measurement থেকে সংখ্যা আলাদা করে (cm এককে, MUST HAVE)
- ply: Ply সংখ্যা (MUST HAVE)
- qty: Order Quantity (MUST HAVE, সংখ্যা হিসেবে)
- pack_type: Pre-Pack বা Pack Type সংক্রান্ত ভ্যালু। PDF-এ এই কলাম না থাকলে "N/A"
- reference: Reference/SKU নম্বর। PDF-এ না থাকলে "N/A"
- color: গার্মেন্টস কালার। না থাকলে "N/A"
- size: গার্মেন্টস সাইজ। না থাকলে "N/A"
- delivery_date: ডেলিভারি ডেট থাকলে (YYYY-MM-DD বা যেভাবে লেখা আছে), না থাকলে "N/A"

এছাড়াও document-এর উপরের অংশ থেকে এই হেডার তথ্যগুলো আলাদাভাবে দাও:
- po_number: PO No. (উপরের কভার পেজ থেকে)
- customer: যে কোম্পানি এই PO ইস্যু করেছে (লেটারহেডের কোম্পানির নাম)
- buyer: Garments Buyer / Brand নাম

**শুধু নিচের JSON ফরম্যাটে উত্তর দাও, আর কোনো টেক্সট/ব্যাখ্যা/মার্কডাউন ব্যাকটিক ছাড়া:**
{
  "header": {"po_number": "", "customer": "", "buyer": ""},
  "line_items": [
    {"item_name": "", "po_no": "", "ewo_no": "", "style_no": "", "length": "", "width": "", "height": "",
     "ply": "", "qty": "", "pack_type": "N/A", "reference": "N/A", "color": "N/A", "size": "N/A", "delivery_date": "N/A"}
  ]
}
"""


def extract_with_ai(pdf_bytes: bytes) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY সেট করা নেই। Replit-এ Secrets ট্যাব থেকে এটা যোগ করুন।"
        )

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "model": MODEL,
        "max_tokens": 8000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()

    # strip accidental ```json fences
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI থেকে সঠিক JSON পাওয়া যায়নি: {e}\n\nRaw: {raw_text[:500]}")

    missing_required = []
    for i, item in enumerate(parsed.get("line_items", [])):
        for field in ("po_no", "ewo_no", "style_no", "length", "width", "height", "ply", "qty"):
            if not str(item.get(field, "")).strip():
                missing_required.append(f"Row {i+1}: {field} খালি")

    parsed["_warnings"] = missing_required
    return parsed
