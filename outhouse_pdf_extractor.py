import re
import pdfplumber


def clean(v):
    if v is None:
        return ''
    return re.sub(r'\s+', ' ', str(v)).strip()


# টাইটেল রো থেকে Job No / Style No / Po No বের করার প্যাটার্ন। এই ফরম্যাটে
# ("Multiple Job Wise Trims Booking V2") প্রতিটা Job/Style ব্লকের শুরুতে
# একটাই লম্বা লাইনে সব তথ্য থাকে, যেমন:
#   "Size Sensitive (Job NO:BTL-26-00399) Style NO:2502 Int Ref.: Po Qty..:18000 Po No: 111043-1 LC/SC:"
#   "NO sensitive (Job NO:BTL-26-00399) Style NO:2502 Int Ref.: Po Qty.: 18000 Po No: 111043-1 LC/SC:"
_TITLE_RE = re.compile(
    r'(Size\s*Sensitive|NO\s*sensitive)\s*\(\s*Job\s*NO\s*:\s*([^)]+)\)\s*'
    r'Style\s*NO\s*:\s*(\S+).*?Po\s*No\s*:\s*([^L]+?)\s*LC/SC',
    re.I,
)

# Item Description-এর মধ্যে থাকা মেজারমেন্ট বের করার প্যাটার্ন, যেমন:
#   "L55 X W35 X H16 CM"  অথবা  "L53 X W33 CM" (Top/Btm-এ Height থাকে না)
_MEASUREMENT_RE = re.compile(
    r'L\s*[-]?\s*(\d+(?:\.\d+)?)\s*X\s*W\s*[-]?\s*(\d+(?:\.\d+)?)'
    r'(?:\s*X\s*H\s*[-]?\s*(\d+(?:\.\d+)?))?',
    re.I,
)


def _parse_title(text):
    m = _TITLE_RE.search(text)
    if not m:
        return None
    block_kind = 'size_sensitive' if 'size' in m.group(1).lower() else 'no_sensitive'
    return {
        'block_kind': block_kind,
        'job_no': clean(m.group(2)),
        'style_no': clean(m.group(3)),
        'po_no': clean(m.group(4)),
    }


def extract_barnali_line_items(pdf):
    """'Multiple Job Wise Trims Booking V2' ফরম্যাটের PDF (যেমন Barnali
    Textile-এর OUT-HOUSE বুকিং) থেকে লাইন-আইটেম বের করে।

    এই PDF-এ প্রতিটা Job/Style ব্লকে দুটো সাব-টেবিল থাকে:
    - 'Size Sensitive'  -> Item Group 'Carton'         -> Item Name 'Master Carton', Ply 5
    - 'NO sensitive'    -> Item Group 'Carton Top/Btm' -> Item Name 'Top Bottom',    Ply 3

    কৌশল: pdfplumber-এর টেবিল এক্সট্র্যাকশনে এই নির্দিষ্ট PDF-এ পাতা-ভেদে
    কলাম-বাউন্ডারি সামান্য শিফট হয় (এক পাতায় যেই কলাম index 6-এ থাকে,
    আরেক পাতায় সেটা 7-এ চলে যায়) — তাই exact column index-এর ওপর ভরসা না
    করে, প্রতিটা রো-তে "ল্যান্ডমার্ক" মান (মেজারমেন্ট প্যাটার্ন, আর 'Pcs'
    টেক্সট) খুঁজে সেগুলোর সাপেক্ষে ডাটা বের করা হচ্ছে — এটা কলাম-শিফট হলেও
    ঠিক কাজ করে।

    Style No/PO No/Job No ব্লক-টাইটেল থেকে আসে (প্রতিটা সাইজ-ভ্যারিয়েন্ট
    রো-তে এগুলো repeat হয় না, তাই ব্লক-লেভেলে ধরে রেখে প্রতিটা ডাটা রো-তে
    বসানো হয় — অনেকটা forward-fill-এর মতোই)।
    """
    line_items = []
    current_block = None
    current_item_group = ''

    for page in pdf.pages:
        for t in page.extract_tables():
            for row in t:
                if not row or all(c is None for c in row):
                    continue
                first_cell = clean(row[0])

                parsed_title = _parse_title(first_cell)
                if parsed_title:
                    current_block = parsed_title
                    current_item_group = ''
                    continue

                if first_cell == 'Sl' or first_cell.startswith('Sl '):
                    continue  # কলাম-হেডার রো

                row_text_joined = ' '.join(clean(c) for c in row if c is not None).lower()
                if 'item total' in row_text_joined:
                    continue
                if first_cell == 'Total':
                    continue

                if current_block is None:
                    continue

                # Item Group (Carton / Carton Top/Btm) শুধু প্রতি গ্রুপের প্রথম
                # রো-তে থাকে, বাকিগুলোয় ফাঁকা — ফরওয়ার্ড-ফিল করা হচ্ছে
                row_item_group = clean(row[1]) if len(row) > 1 else ''
                if row_item_group:
                    current_item_group = row_item_group
                if not current_item_group:
                    continue

                measurement_match = None
                for c in row:
                    if c is None:
                        continue
                    mm = _MEASUREMENT_RE.search(str(c))
                    if mm:
                        measurement_match = mm
                        break
                if not measurement_match:
                    continue  # ডাটা রো না (সম্ভবত কোনো সামারি/অন্য লাইন)

                length = measurement_match.group(1)
                width = measurement_match.group(2)
                height = measurement_match.group(3) or ''

                # Qty: 'Pcs'-এর ঠিক আগের non-blank ভ্যালুটাই কোয়ান্টিটি
                # (Size Sensitive-এ 'WO Qty.', NO sensitive-এ 'Qnty' — কলামের
                # নাম আলাদা হলেও পজিশন সবসময় 'Pcs'-এর ঠিক আগেই থাকে)
                non_blank = [clean(c) for c in row if c is not None and clean(c) != '']
                qty = ''
                if 'Pcs' in non_blank:
                    pcs_idx = non_blank.index('Pcs')
                    if pcs_idx > 0:
                        qty = non_blank[pcs_idx - 1]

                is_top_bottom = 'top' in current_item_group.lower()
                item_name = 'Top Bottom' if is_top_bottom else 'Master Carton'
                ply = '3' if is_top_bottom else '5'

                line_items.append({
                    'item_name': item_name,
                    'ewo_no': 'N/A',
                    'style_no': current_block['style_no'],
                    'po_no': current_block['po_no'],
                    'length': length,
                    'width': width,
                    'height': height,
                    'ply': ply,
                    'qty': qty,
                    'pack_type': '',
                    # ইউজারের নির্দেশ অনুযায়ী — Job No -> Reference/SKU Number
                    'reference': current_block['job_no'],
                    'color': '',
                    'size': '',
                    'delivery_date': '',
                    'measurement_unit': 'Cm',
                    'delivery_place_pdf': '',
                    'delivery_address_pdf': '',
                })

    return line_items


def _significant_words(s):
    """তুলনা করার জন্য 'Ltd/Pvt/Industries/Group' জাতীয় সাধারণ কোম্পানি-সাফিক্স
    শব্দ বাদ দিয়ে শুধু আসল/স্বতন্ত্র শব্দগুলো বের করে (case-insensitive)।"""
    stop = {'ltd', 'pvt', 'limited', 'industries', 'ind', 'and', 'the', 'co',
            'company', 'group', 'ab', 'inc', 'corp', 'corporation', 'private', 'new'}
    words = re.findall(r'[a-zA-Z]+', s.lower())
    return set(w for w in words if w not in stop and len(w) > 2)


def _fuzzy_match_from_list(text, candidates):
    """PDF থেকে বের করা raw টেক্সট (যেমন 'Barnali Textile and Printing Ind')
    আমাদের ফিক্সড লিস্টের (যেমন 'Barnali Textile and Printing Industries
    (Pvt) Ltd.') কোনটার সাথে সবচেয়ে বেশি মেলে সেটা খুঁজে বের করে —
    case-sensitive হুবহু মেলার দরকার নেই, PDF-ভেদে সংক্ষিপ্ত/ভিন্ন
    বানান (Ind vs Industries) থাকলেও কাজ করে। মিল ৫০%-এর কম হলে None।"""
    if not text or not candidates:
        return None
    text_words = _significant_words(text)
    if not text_words:
        return None
    best, best_score = None, 0.0
    for cand in candidates:
        cand_words = _significant_words(cand)
        if not cand_words:
            continue
        overlap = len(cand_words & text_words)
        score = overlap / len(cand_words)
        if score > best_score:
            best_score = score
            best = cand
    return best if best_score >= 0.5 else None


def extract_barnali_header_info(pdf, known_customers=None, known_buyers=None):
    """এই ফরম্যাটের PDF-এর প্রথম পাতা থেকে Booking No (-> PO Number),
    Buyer, এবং Customer (vendor company name) বের করে — পাওয়া গেলে
    known_customers/known_buyers লিস্টের সাথে fuzzy ম্যাচ করে ক্যানোনিকাল
    নামে বসিয়ে দেয় (case-insensitive, ছোটখাটো বানান-ভিন্নতা সহ্য করে)।"""
    text = pdf.pages[0].extract_text() or ''

    booking_no_m = re.search(r'Booking\s*No\s*:\s*(\S+)', text)
    booking_no = booking_no_m.group(1).strip() if booking_no_m else ''

    buyer_m = re.search(r'Buyer\.?\s*:\s*(.+?)\s+Delivery Date', text)
    buyer_raw = buyer_m.group(1).strip() if buyer_m else ''

    customer_m = re.search(r'^(.+?)\s*Booking\s*No\s*:', text, re.DOTALL)
    customer_raw = re.sub(r'\s+', ' ', customer_m.group(1)).strip() if customer_m else ''

    customer_matched = _fuzzy_match_from_list(customer_raw, known_customers or [])
    buyer_matched = _fuzzy_match_from_list(buyer_raw, known_buyers or [])

    return {
        'po_number': booking_no,
        'customer': customer_matched or customer_raw,
        'buyer': buyer_matched or buyer_raw,
    }


def process_barnali_pdf(file_stream, known_customers=None, known_buyers=None):
    """এন্ট্রি পয়েন্ট — Returns (header_info, line_items)।
    header_info: {'po_number', 'customer', 'buyer'} — Booking No/Buyer/Customer
    অটো-এক্সট্র্যাক্ট করে, known_customers/known_buyers দেওয়া থাকলে
    ফাজি-ম্যাচ করে ক্যানোনিকাল নামে বসিয়ে দেয়।
    line_items: canonical schema (builder.py-এর build_combined_excel সরাসরি
    এটা নিতে পারবে, প্রোফাইল='OUT-HOUSE')।
    """
    with pdfplumber.open(file_stream) as pdf:
        header_info = extract_barnali_header_info(pdf, known_customers, known_buyers)
        line_items = extract_barnali_line_items(pdf)
    return header_info, line_items