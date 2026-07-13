import re
import pdfplumber
import pandas as pd

# Header extraction (PO No/Customer/Buyer) is byte-for-byte identical to the
# Carton module's cover-page format, so it's reused as-is.
from extractor import clean, extract_header_info

SUMMARY_HEADER_MARKERS = {'ST Caow', 'PT Caow', 'Sticker Type'}


def extract_summary_table_thermal(pdf):
    """Thermal PO-এর page0-এ থাকা রেট-সামারি টেবিলটা বের করে আনে। বায়ার/আইটেম
    ভেদে প্রথম কলামের নাম ভিন্ন হয় ('ST Caow' / 'PT Caow' / 'Sticker Type') —
    তাই একটা সেট দিয়ে ম্যাচ করা হচ্ছে, single hardcoded নামের বদলে।"""
    for page in pdf.pages:
        for t in page.extract_tables():
            if t and t[0] and clean(t[0][0]) in SUMMARY_HEADER_MARKERS:
                header = [clean(h) for h in t[0]]
                rows = [[clean(c) for c in r] for r in t[1:]
                        if r and r[0] and clean(r[0]).lower() not in
                        ('pcs wise total', 'pcs wise total qty', 'total', 'total value')]
                return pd.DataFrame(rows, columns=header)
    return pd.DataFrame()


def _to_float(v):
    v = clean(v).replace(',', '')
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _norm(s):
    """সব হোয়াইটস্পেস (এমনকি শব্দের মাঝখানের লাইন-ব্রেকও) মুছে lowercase করে —
    PDF কখনো কখনো সরু কলামে শব্দ মাঝপথে ভেঙে ফেলে (যেমন 'Sticker' -> 'Stick\\ner')
    — এই নরমালাইজেশন সেই সমস্যা এড়িয়ে সঠিক কলামে ম্যাচ করায়।"""
    return re.sub(r'\s+', '', str(s or '')).lower()


# 'GS=XS', 'gs = S', 'Size: M' ইত্যাদির মতো যেকোনো ছোট আলফাবেটিক প্রিফিক্স +
# '=' বা ':' — সাইজ লেবেলের আগে থাকলে বাদ দেওয়ার জন্য। শব্দের মাঝে '=' চিহ্ন
# সাধারণত সাইজ কোডে থাকে না, তাই এটা নিরাপদে সব ফরম্যাটে প্রয়োগ করা যায়।
_SIZE_PREFIX_RE = re.compile(r'^[A-Za-z]{1,5}\s*[:=]\s*', re.I)


def _clean_size_label(raw):
    """সাইজ লেবেল থেকে 'GS=' জাতীয় প্রিফিক্স বাদ দেয় এবং ফাঁকা হলে 'N/A' রিটার্ন
    করে। দুইবার (extractor-এ আর builder-এ কল হওয়ার সময়) প্রয়োগ করা নিরাপদ —
    ইতিমধ্যে পরিষ্কার থাকা লেবেলের ক্ষেত্রে এটা কোনো পরিবর্তন করে না।"""
    s = clean(raw)
    s = _SIZE_PREFIX_RE.sub('', s).strip()
    return s if s else 'N/A'


THERMAL_FIELD_MAP = {
    _norm('EWO No'): 'EWO No',
    _norm('Style No'): 'Style No',
    _norm('Sticker Caow'): 'Sticker Caow',
    _norm('Sticker Reference'): 'Sticker Reference',
    _norm('PT Caow'): 'PT Caow',
    _norm('PT Reference'): 'PT Reference',
    _norm('Sticker Type'): 'Sticker Type',
    _norm('Code / Reference'): 'Code / Reference',
    _norm('Pre Pack'): 'Pre Pack',
    _norm('PONo'): 'PONo',
    _norm('PO No'): 'PONo',
    _norm('PO QTY'): 'PO QTY',
    _norm('POQty'): 'PO QTY',
    _norm('Gmt. Color'): 'Gmt. Color',
    _norm('Color'): 'Color',
    _norm('Instruction'): 'Instruction',
    _norm('Country'): 'Country',
    _norm('Length (cm)'): 'Length (cm)',
    _norm('Width (cm)'): 'Width (cm)',
    _norm('Delivery Place'): 'Delivery Place',
    _norm('Delivery Address'): 'Delivery Address',
    _norm('Delivery Start Date'): 'Delivery Start Date',
    _norm('Delivery End Date'): 'Delivery End Date',
    _norm('UOM'): 'UOM',
}


def _canonical_field_names(raw_names):
    return [THERMAL_FIELD_MAP.get(_norm(n), n) for n in raw_names]


_SUMMARY_ROW_MARKERS = ('pcs wise total', 'pcs wise total qty', 'total', 'total value')


def extract_detail_rows_thermal(pdf):
    """Thermal PO-এর 'Purchase Order Details' টেবিল বের করে আনে। এখন পর্যন্ত
    দেখা গেছে দুই ধরনের ফরম্যাট আছে:

    (ক) WIDE — 'Size/Measurement' হেডিং দিয়ে শুরু, প্রতিটা সাইজ (XS,S,M,L...)
        আলাদা কলামে (Stanley Stella, Tommy Hilfiger)। কিছু বায়ারের সাইজ-হেডারে
        'GS=' প্রিফিক্স থাকে (যেমন 'GS=XS') — সেটা বাদ দিয়ে শুধু আসল সাইজ লেবেল
        রাখা হয়। কোনো বায়ারের ক্ষেত্রে সাইজ-কলাম আসলে ফাঁকা/অস্তিত্বহীন হলে
        (M&S — শুধু 'GS=' আর 'Total', মাঝে কোনো সাইজ নাম নেই), সেটাকে
        "সাইজ নেই" হিসেবে ধরে Size='N/A' বসানো হয়।
    (খ) FLAT — কোনো 'Size/Measurement' হেডিং নেই, প্রথম রো-ই সরাসরি ফিল্ড
        হেডার (EWO No, Style No, ...PO QTY...) — Varner-এর Carton Sticker
        ফরম্যাট। এখানে প্রতিটা রো = এক লাইন-আইটেম, Size='N/A', Qty = PO QTY কলাম।

    টেবিল multi-page হতে পারে (Varner/M&S-এ ৩-৪ পাতা জুড়ে ছড়ানো) — pdfplumber
    প্রতিটা পাতার জন্য আলাদা টেবিল অবজেক্ট রিটার্ন করে, কিন্তু হেডার রো শুধু
    প্রথম পাতাতেই থাকে, পরের পাতাগুলোতে হেডার রিপিট হয় না — তাই হেডার একবার
    ঠিক হয়ে গেলে পরের সব টেবিলকে বিশুদ্ধ ডাটা-continuation হিসেবে ধরা হয়।

    Reference/SKU Number-এর সোর্স কলাম বায়ার-ভেদে ভিন্ন (Varner: 'Pre Pack',
    বাকিরা: 'Instruction', M&S-এ Instruction না থাকলে 'Code / Reference') —
    তাই একটা প্রায়োরিটি-চেইন দিয়ে বাছাই করা হয়, যেটাই ওই ফরম্যাটে বাস্তবে
    উপস্থিত ও অর্থপূর্ণ, সেটাই ব্যবহার হবে।

    Returns (line_items_df, raw_wide_df).
    """
    field_names = None
    size_labels = None
    split_idx = None
    is_wide = False
    raw_wide_rows = []
    melted = []
    last_ewo, last_style = '', ''

    def process_data_row(row):
        nonlocal last_ewo, last_style
        if not row:
            return
        first_cell = clean(row[0]) if row[0] else ''
        if first_cell.lower() in _SUMMARY_ROW_MARKERS:
            return  # সামারি রো — লাইন-আইটেম না

        meta_vals = [clean(v) for v in row[:len(field_names)]]
        meta = dict(zip(field_names, meta_vals))

        if meta.get('EWO No'):
            last_ewo = meta['EWO No']
        else:
            meta['EWO No'] = last_ewo
        if meta.get('Style No'):
            last_style = meta['Style No']
        else:
            meta['Style No'] = last_style

        meta['Reference'] = meta.get('Pre Pack') or meta.get('Instruction') or meta.get('Code / Reference') or ''

        if is_wide and size_labels:
            qty_cells = row[split_idx:split_idx + len(size_labels)]
            raw_wide_rows.append({**meta, **{
                (size_labels[i] or f'Size{i+1}'): clean(qty_cells[i]) if i < len(qty_cells) else ''
                for i in range(len(size_labels))
            }})
            for i, size_label in enumerate(size_labels):
                qv = _to_float(qty_cells[i]) if i < len(qty_cells) else None
                if qv is None:
                    continue
                melted.append({**meta, 'Size': _clean_size_label(size_label), 'Qty': qv})
        else:
            qty = _to_float(meta.get('PO QTY', ''))
            raw_wide_rows.append(dict(meta))
            melted.append({**meta, 'Size': 'N/A', 'Qty': qty})

    for page in pdf.pages:
        for t in page.extract_tables():
            if not t or not t[0]:
                continue
            if clean(t[0][0]) in SUMMARY_HEADER_MARKERS:
                continue  # এটা page0-এর রেট-সামারি টেবিল, ডিটেল টেবিল না — স্কিপ
            rows = t
            if rows[0] and clean(rows[0][0]) == 'Purchase Order Details':
                rows = rows[1:]
            if not rows:
                continue

            if field_names is None:
                row0 = rows[0]
                c0 = clean(row0[0]) if row0 and row0[0] else ''
                if c0 == 'Size/Measurement':
                    size_row = row0
                    field_row = rows[1] if len(rows) > 1 else []
                    for i, v in enumerate(size_row):
                        if i == 0:
                            continue
                        if clean(v):
                            split_idx = i
                            break
                    if split_idx is None:
                        continue
                    raw_sizes = [clean(v) for v in size_row[split_idx:]]
                    raw_sizes = [s for s in raw_sizes if s and s.lower() != 'total']
                    size_labels = [_clean_size_label(s) for s in raw_sizes]
                    is_wide = True
                    field_names = _canonical_field_names([clean(v) for v in field_row[:split_idx]])
                    for r in rows[2:]:
                        process_data_row(r)
                else:
                    is_wide = False
                    field_names = _canonical_field_names([clean(v) for v in row0])
                    for r in rows[1:]:
                        process_data_row(r)
            else:
                for r in rows:
                    process_data_row(r)

    if field_names is None:
        raise ValueError("এই PDF-এ পরিচিত Thermal 'Purchase Order Details' টেবিল ফরম্যাট পাওয়া যায়নি।")

    line_items_df = pd.DataFrame(melted)
    raw_wide_df = pd.DataFrame(raw_wide_rows)
    return line_items_df, raw_wide_df


def _rate_lookup(summary_df):
    """summary_df (page0-এর রেট-সামারি টেবিল) থেকে (কোড, রেফারেন্স) -> Rate
    ম্যাপ বানায়। summary-তে যদি একটাই রো থাকে (এখন পর্যন্ত দেখা সব PO-তেই তাই),
    সব লাইন-আইটেমের জন্য সেই একটা Rate-ই সরাসরি ব্যবহার করা হয় — এটাই প্রধান পথ।
    একাধিক রো থাকলে প্রথম দুই কলামের মান দিয়ে (নাম যা-ই হোক) ম্যাচ করার চেষ্টা হয়।"""
    if summary_df is None or summary_df.empty:
        return {}, None
    if len(summary_df) == 1:
        return {}, summary_df.iloc[0].get('Rate', '')
    lookup = {}
    cols = list(summary_df.columns)
    for _, r in summary_df.iterrows():
        key = tuple(clean(r.get(c, '')) for c in cols[:2])
        lookup[key] = r.get('Rate', '')
    return lookup, None


def to_canonical_thermal(df, summary_df=None):
    """মেল্ট/ফ্ল্যাট করা DataFrame-কে canonical line-item স্কিমায় রূপান্তর করে,
    যেটা thermal_builder.py ব্যবহার করবে।"""
    rate_lookup, single_rate = _rate_lookup(summary_df)
    summary_cols = list(summary_df.columns)[:2] if summary_df is not None and not summary_df.empty else []
    line_items = []
    for _, r in df.iterrows():
        if single_rate is not None:
            rate = single_rate
        else:
            key = tuple(clean(r.get(c, '')) for c in summary_cols) if summary_cols else ()
            rate = rate_lookup.get(key, '')
        line_items.append({
            'ewo_no': r.get('EWO No', ''),
            'style_no': r.get('Style No', ''),
            'po_no': r.get('PONo', ''),
            'color': r.get('Gmt. Color', '') or r.get('Color', ''),
            'reference': r.get('Reference', ''),
            # দ্বিতীয়বার _clean_size_label প্রয়োগ করা হচ্ছে (defense-in-depth) —
            # কোনো কারণে 'GS=' জাতীয় প্রিফিক্স আগের ধাপে ফসকে গেলেও এখানে ধরা পড়বে
            'size': _clean_size_label(r.get('Size', '')),
            'qty': r.get('Qty', ''),
            'uom': r.get('UOM', 'Pcs') or 'Pcs',
            'rate': rate,
            'delivery_date_pdf': r.get('Delivery Start Date', ''),
            'delivery_place_pdf': r.get('Delivery Place', ''),
            'delivery_address_pdf': r.get('Delivery Address', ''),
        })
    return line_items


def get_unique_delivery_info_thermal(raw_wide_df):
    """Carton মডিউলের মতোই — PDF-এ পাওয়া Delivery Place/Address-এর ইউনিক
    ভ্যালুগুলো UI হিন্টের জন্য বের করে দেয়।"""
    def uniques(col):
        if raw_wide_df is None or raw_wide_df.empty or col not in raw_wide_df.columns:
            return []
        seen = []
        for v in raw_wide_df[col]:
            v = clean(v)
            if v and v not in seen:
                seen.append(v)
        return seen

    return {
        'delivery_places': uniques('Delivery Place'),
        'delivery_addresses': uniques('Delivery Address'),
    }


def process_pdf_thermal(file_stream):
    """Thermal মডিউলের মেইন এন্ট্রি পয়েন্ট।
    Returns (header_info, canonical line_items, raw_wide_df, summary_df)."""
    with pdfplumber.open(file_stream) as pdf:
        header_info = extract_header_info(pdf)
        summary_df = extract_summary_table_thermal(pdf)
        melted_df, raw_wide_df = extract_detail_rows_thermal(pdf)
    line_items = to_canonical_thermal(melted_df, summary_df)
    return header_info, line_items, raw_wide_df, summary_df
