import re
import pdfplumber


def clean(v):
    if v is None:
        return ''
    return re.sub(r'\s+', ' ', str(v)).strip()


# টাইটেল রো থেকে Job No / Style No / Po No বের করার প্যাটার্ন। এই PDF-পরিবারে
# ("Multiple Job Wise Trims Booking V2") প্রতিটা Job/Style ব্লকের শুরুতে একটাই
# লম্বা লাইনে সব তথ্য থাকে — buyer/vendor ভেদে prefix লেবেল (Size Sensitive/
# NO sensitive/As Per Garments Color/Color & size sensitive ইত্যাদি) এবং শেষে
# কী দিয়ে থামে (LC/SC: বা Shipment Date:) আলাদা হতে পারে, তাই prefix লেবেল
# উপেক্ষা করে শুধু Job NO/Style NO/Po No প্যাটার্নটাই ধরা হচ্ছে — এটা নতুন
# prefix লেবেল এলেও কাজ করবে।
_TITLE_RE = re.compile(
    r'\(\s*Job\s*NO\s*:\s*([^)]+)\)\s*'
    r'Style\s*NO\s*:\s*(\S+).*?'
    r'Po\s*No\s*:\s*(.+?)\s*(?:LC/SC|Shipment\s*Date|$)',
    re.I,
)

# Item Description-এর মধ্যে থাকা মেজারমেন্ট বের করার দুই ধরনের প্যাটার্ন:
#   (ক) "L55 X W35 X H16 CM"   — L/W/H লেটার-প্রিফিক্সড (Barnali-স্টাইল)
#   (খ) "300X200X160 MM"       — শুধু সংখ্যা×সংখ্যা×সংখ্যা, ইউনিট শেষে (Modele-স্টাইল)
_MEASUREMENT_RE_LETTERED = re.compile(
    r'L\s*[-]?\s*(\d+(?:\.\d+)?)\s*X\s*W\s*[-]?\s*(\d+(?:\.\d+)?)'
    r'(?:\s*X\s*H\s*[-]?\s*(\d+(?:\.\d+)?))?\s*(CM|MM)?',
    re.I,
)
_MEASUREMENT_RE_PLAIN = re.compile(
    r'(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*(CM|MM)?',
    re.I,
)


def _match_measurement(text):
    m = _MEASUREMENT_RE_LETTERED.search(text)
    if m:
        return m.group(1), m.group(2), m.group(3) or '', (m.group(4) or 'CM').upper()
    m = _MEASUREMENT_RE_PLAIN.search(text)
    if m:
        return m.group(1), m.group(2), m.group(3) or '', (m.group(4) or 'CM').upper()
    return None


def _parse_title(text):
    m = _TITLE_RE.search(text)
    if not m:
        return None
    return {
        'job_no': clean(m.group(1)),
        'style_no': clean(m.group(2)),
        'po_no': clean(m.group(3)),
    }


def extract_trims_booking_line_items(pdf):
    """'Multiple Job Wise Trims Booking V2' PDF-পরিবার (Barnali, Modele de
    Capital ইত্যাদি — একই ERP সফটওয়্যার থেকে তৈরি, কিন্তু ভেন্ডর-ভেদে কলাম
    সাজানো/টাইটেল-লেবেল একটু আলাদা) থেকে লাইন-আইটেম বের করে।

    Item Group কলাম অনুযায়ী:
    - 'Carton'          -> Item Name 'Master Carton', ডিফল্ট Ply 5
    - 'Carton Top/Btm'  -> Item Name 'Top Bottom',    ডিফল্ট Ply 3
    (কোনো buyer-এর জন্য Ply ফিক্সড/ওভাররাইড দরকার হলে — যেমন Primark সবসময়
    3-ply — সেটা app.py-তে বায়ার নিশ্চিত হওয়ার পর প্রয়োগ হয়, কারণ
    এক্সট্র্যাকশনের সময় এখনো জানা থাকে না ইউজার শেষমেশ কোন buyer কনফার্ম করবেন)

    কৌশল: এই PDF-পরিবারে পাতা-ভেদে টেবিলের কলাম-বাউন্ডারি সামান্য শিফট হতে
    পারে, তাই exact column index ধরে না রেখে প্রতিটা রো-তে "ল্যান্ডমার্ক"
    মান (মেজারমেন্ট প্যাটার্ন, আর 'Pcs' টেক্সট) খুঁজে সেগুলোর সাপেক্ষে ডাটা
    বের করা হচ্ছে।

    Style No/PO No/Job No ব্লক-টাইটেল থেকে আসে (প্রতিটা সাইজ-ভ্যারিয়েন্ট
    রো-তে এগুলো repeat হয় না, তাই ব্লক-লেভেলে ধরে রেখে প্রতিটা ডাটা রো-তে
    ফরওয়ার্ড-ফিল করে বসানো হয়)।
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

                measurement = None
                for c in row:
                    if c is None:
                        continue
                    measurement = _match_measurement(str(c))
                    if measurement:
                        break
                if not measurement:
                    continue  # ডাটা রো না (সম্ভবত কোনো সামারি/অন্য লাইন)

                length, width, height, unit = measurement

                # Qty: 'Pcs'-এর ঠিক আগের non-blank ভ্যালুটাই কোয়ান্টিটি
                # (কলামের নাম ভিন্ন হতে পারে — 'WO Qty.'/'WO Qty'/'Qnty' —
                # কিন্তু পজিশন সবসময় 'Pcs'-এর ঠিক আগেই থাকে)।
                # কিছু পাতায় pdfplumber সংখ্যার শেষ ডিজিট 'Pcs'-এর সাথে জুড়ে
                # দেয় (যেমন '51.0000 Pcs' -> '51.000' + '0 Pcs') — সেই
                # গ্লিচ ধরে সঠিক সংখ্যাটা পুনর্গঠন করা হচ্ছে।
                non_blank = [clean(c) for c in row if c is not None and clean(c) != '']
                qty = ''
                pcs_idx = None
                pcs_prefix = ''
                for i, val in enumerate(non_blank):
                    pm = re.match(r'^(\d*)\s*Pcs$', val, re.I)
                    if pm:
                        pcs_idx = i
                        pcs_prefix = pm.group(1)
                        break
                if pcs_idx is not None and pcs_idx > 0:
                    qty = non_blank[pcs_idx - 1] + pcs_prefix

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
                    'measurement_unit': unit.title(),
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
    """PDF থেকে বের করা raw টেক্সট আমাদের ফিক্সড লিস্টের কোনটার সাথে সবচেয়ে
    বেশি মেলে সেটা খুঁজে বের করে — case-sensitive হুবহু মেলার দরকার নেই।
    মিল ৫০%-এর কম হলে None (তখন ইউজারকে ম্যানুয়ালি বসাতে হবে)।"""
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


def extract_trims_booking_header_info(pdf, known_customers=None, known_buyers=None):
    """এই PDF-পরিবারের প্রথম পাতা থেকে Booking No (-> PO Number), Buyer,
    এবং Customer (vendor company name) বের করে — known_customers/
    known_buyers লিস্টের সাথে fuzzy ম্যাচ করে ক্যানোনিকাল নামে বসিয়ে দেয়।
    কোনোটার সাথে মিল না পেলে (৫০%-এর কম) সেটা ফাঁকা রাখা হয় — যাতে ইউজার
    বুঝতে পারেন ম্যানুয়ালি লিস্ট থেকে বসাতে হবে, ভুল/আধা-মেলা নাম না বসে।"""
    text = pdf.pages[0].extract_text() or ''

    booking_no_m = re.search(r'Booking\s*No\s*:\s*(\S+)', text)
    booking_no = booking_no_m.group(1).strip() if booking_no_m else ''

    buyer_m = re.search(r'Buyer\.?\s*:\s*(.+?)\s+(?:Delivery Date|PO Qty)', text)
    buyer_raw = buyer_m.group(1).strip() if buyer_m else ''

    customer_m = re.search(r'^(.+?)\s*Booking\s*No\s*:', text, re.DOTALL)
    customer_raw = re.sub(r'\s+', ' ', customer_m.group(1)).strip() if customer_m else ''

    customer_matched = _fuzzy_match_from_list(customer_raw, known_customers or [])
    buyer_matched = _fuzzy_match_from_list(buyer_raw, known_buyers or [])

    return {
        'po_number': booking_no,
        'customer': customer_matched or '',
        'buyer': buyer_matched or '',
    }


def process_trims_booking_pdf(file_stream, known_customers=None, known_buyers=None):
    """এন্ট্রি পয়েন্ট — Returns (header_info, line_items)।
    header_info: {'po_number', 'customer', 'buyer'} — মিল না পেলে ফাঁকা স্ট্রিং।
    line_items: canonical schema (builder.py-এর build_combined_excel সরাসরি
    এটা নিতে পারবে, প্রোফাইল='OUT-HOUSE')।
    """
    with pdfplumber.open(file_stream) as pdf:
        header_info = extract_trims_booking_header_info(pdf, known_customers, known_buyers)
        line_items = extract_trims_booking_line_items(pdf)
    return header_info, line_items
