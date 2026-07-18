import io
import os
import re
import tempfile

from flask import Flask, request, render_template, send_file, jsonify

from extractor import process_pdf_rule_based, get_unique_delivery_info
from builder import build_combined_excel, validate_line_items
from outhouse_extractor import combine_booking_excels
from outhouse_pdf_extractor import process_trims_booking_pdf
from thermal_extractor import process_pdf_thermal, get_unique_delivery_info_thermal
from thermal_builder import build_thermal_excel, validate_thermal_line_items
from thermal_config import THERMAL_BUYERS, THERMAL_BUYER_ALIASES, THERMAL_VERIFIED_BUYERS
from validators import (
    validate_customer, validate_buyer, validate_buyer_in_list, validate_po_number,
    validate_delivery_address, validate_matches_pdf, values_match_ci,
)
from date_logic import get_default_delivery_date, validate_manual_delivery_date, format_delivery_date
from config import (
    CUSTOMERS, BUYERS, DELIVERY_ADDRESSES, BUYER_ALIASES, CUSTOMER_ALIASES,
    CARTON_VERIFIED_BUYERS, OUTHOUSE_CUSTOMER_BUYERS, OUTHOUSE_AUTO_ITEM_PLY_COMBOS,
    resolve_alias,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB


@app.route('/')
def modules_home():
    """সব মডিউলের লিস্ট — এখান থেকে ক্লিক করে ভেতরের মডিউলে ঢোকা যাবে।"""
    return render_template('modules.html')


@app.route('/autocarton')
def autocarton_index():
    return render_template(
        'index.html',
        customers=CUSTOMERS,
        buyers=BUYERS,
        delivery_addresses=DELIVERY_ADDRESSES,
        outhouse_customer_buyers=OUTHOUSE_CUSTOMER_BUYERS,
        outhouse_auto_item_ply_combos=OUTHOUSE_AUTO_ITEM_PLY_COMBOS,
    )


@app.route('/thermal')
def thermal_index():
    return render_template(
        'thermal.html',
        customers=CUSTOMERS,
        buyers=THERMAL_BUYERS,
        delivery_addresses=DELIVERY_ADDRESSES,
    )


@app.route('/extract_header', methods=['POST'])
def extract_header():
    """PDF আপলোড হওয়ার সাথে সাথেই (ফর্ম সাবমিটের আগেই) শুধু হেডার তথ্য
    (PO Number/Customer/Buyer) বের করে ফেরত দেয়, যাতে ফ্রন্টএন্ড সাথে সাথে
    এগুলো ফিল্ডে বসিয়ে দিতে পারে। এখানে কোনো Excel বানানো হয় না, শুধু
    দ্রুত extract করে JSON রিটার্ন করে।"""
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDF ফাইল পাওয়া যায়নি'}), 400

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({'error': 'ফাইল সিলেক্ট করা হয়নি'}), 400

    pdf_bytes_raw = pdf_file.read()
    try:
        header_info, line_items, raw_df, summary_df = process_pdf_rule_based(io.BytesIO(pdf_bytes_raw))
    except Exception as e:
        return jsonify({'error': f'PDF থেকে তথ্য বের করতে সমস্যা হয়েছে: {str(e)}'}), 422

    # PDF-এ 'M&S', 'DEKKO KNITWEARS LTD.'-এর মতো সংক্ষিপ্ত/ভিন্ন নাম থাকলে এখানেই
    # config.py-এর BUYER_ALIASES/CUSTOMER_ALIASES দিয়ে ক্যানোনিকাল নামে বদলে দেওয়া
    # হচ্ছে — যাতে ফ্রন্টএন্ডের ফিল্ড ঠিকভাবে অটো-লক হয় এবং পরে /process-এ
    # মিসম্যাচ এরর না আসে।
    header_info['buyer'] = resolve_alias(header_info.get('buyer', ''), BUYER_ALIASES)
    header_info['customer'] = resolve_alias(header_info.get('customer', ''), CUSTOMER_ALIASES)

    delivery_info = get_unique_delivery_info(raw_df)

    return jsonify({
        'po_number': header_info.get('po_number', '') or '',
        'customer': header_info.get('customer', '') or '',
        'buyer': header_info.get('buyer', '') or '',
        'delivery_places_pdf': delivery_info['delivery_places'],
        'delivery_addresses_pdf': delivery_info['delivery_addresses'],
    })


@app.route('/process', methods=['POST'])
def process():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDF ফাইল পাওয়া যায়নি'}), 400

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({'error': 'ফাইল সিলেক্ট করা হয়নি'}), 400

    customer_type = request.form.get('customer_type', 'IN-HOUSE').strip()
    customer_name = request.form.get('customer_name', '').strip()
    buyer_name = request.form.get('buyer_name', '').strip()
    po_number_override = request.form.get('po_number', '').strip()
    delivery_mode = request.form.get('delivery_mode', 'auto').strip()
    delivery_date_manual = request.form.get('delivery_date', '').strip()
    delivery_address = request.form.get('delivery_address', '').strip()
    method = request.form.get('method', 'rule_based')
    remark_place = request.form.get('remark_place', '').strip().lower() in ('1', 'true', 'on', 'yes')
    remark_address = request.form.get('remark_address', '').strip().lower() in ('1', 'true', 'on', 'yes')
    # ইমারজেন্সি ফোর্স ওভাররাইড: চেক করা থাকলে PDF-এর সাথে Customer/Buyer না
    # মিললেও এরর দেওয়া হবে না, ম্যানুয়ালি দেওয়া নামটাই ব্যবহার হবে (ERP লিস্টের
    # সাথে case-sensitive মেলার শর্ত অবশ্য তখনও বহাল থাকবে)।
    force_override = request.form.get('force_override', '').strip().lower() in ('1', 'true', 'on', 'yes')

    # --- Buyer বাধ্যতামূলক ও case-sensitive লিস্ট-ম্যাচ ---
    buyer_error = validate_buyer(buyer_name)
    if buyer_error:
        return jsonify({'error': buyer_error}), 422

    # --- Customer আবশ্যক ও case-sensitive লিস্ট-ম্যাচ ---
    customer_error = validate_customer(customer_type, customer_name)
    if customer_error:
        return jsonify({'error': customer_error}), 422

    # --- Delivery Address: যে Customer-এর জন্য address লিস্ট configure করা আছে, তার জন্য আবশ্যক ---
    address_error = validate_delivery_address(customer_name, delivery_address)
    if address_error:
        return jsonify({'error': address_error}), 422

    # --- Delivery Date: manual হলে আগেই ভ্যালিডেট করে নেওয়া (PDF পড়ার আগে, সময় বাঁচাতে) ---
    if delivery_mode == 'manual':
        is_valid, err, parsed_date = validate_manual_delivery_date(delivery_date_manual)
        if not is_valid:
            return jsonify({'error': err}), 422
        delivery_date_final = format_delivery_date(parsed_date)
    else:
        delivery_date_final = format_delivery_date(get_default_delivery_date())

    pdf_bytes_raw = pdf_file.read()

    # --- Method: Rule-Based (active) ---
    if method == 'rule_based':
        try:
            header_info, line_items, raw_df, summary_df = process_pdf_rule_based(io.BytesIO(pdf_bytes_raw))
        except Exception as e:
            return jsonify({'error': f'PDF পড়তে সমস্যা হয়েছে (rule-based): {str(e)}'}), 422

    # --- Method: AI-Based (coming soon, not wired in yet) ---
    elif method == 'ai_based':
        return jsonify({
            'error': 'AI-Based মেথড এখনো চালু করা হয়নি। শীঘ্রই আসছে — আপাতত Rule-Based ব্যবহার করুন।'
        }), 501

    else:
        return jsonify({'error': f'অজানা মেথড: {method}'}), 400

    if not line_items:
        return jsonify({'error': 'কোনো লাইন-আইটেম পাওয়া যায়নি এই PDF থেকে'}), 422

    # PDF-এ 'M&S', 'DEKKO KNITWEARS LTD.'-এর মতো সংক্ষিপ্ত/ভিন্ন নাম থাকলে এখানেই
    # ক্যানোনিকাল নামে বদলে দেওয়া হচ্ছে, নিচের মিসম্যাচ-চেকের আগে — তাই আসল লেখা
    # ভিন্ন হলেও (কিন্তু আমাদের অ্যালিয়াস লিস্টে থাকলে) এরর আসবে না।
    header_info['buyer'] = resolve_alias(header_info.get('buyer', ''), BUYER_ALIASES)
    header_info['customer'] = resolve_alias(header_info.get('customer', ''), CUSTOMER_ALIASES)

    # --- PO Number / Customer / Buyer: PDF-এর সাথে (case-insensitive) মিল থাকতে হবে ---
    po_error = validate_po_number(po_number_override, header_info.get('po_number', ''))
    if po_error:
        return jsonify({'error': po_error}), 422

    customer_pdf_error = None if force_override else validate_matches_pdf(
        'Customer', customer_name, header_info.get('customer', ''))
    if customer_pdf_error:
        return jsonify({'error': customer_pdf_error}), 422

    buyer_pdf_error = None if force_override else validate_matches_pdf(
        'Buyer', buyer_name, header_info.get('buyer', ''))
    if buyer_pdf_error:
        return jsonify({'error': buyer_pdf_error}), 422

    warnings = validate_line_items(line_items)

    # buyer সিস্টেমে (মাস্টার লিস্টে) থাকলেই যথেষ্ট প্রসেসিং চালানোর জন্য —
    # কিন্তু এই buyer-এর Carton PDF ফরম্যাট এখনো নির্দিষ্টভাবে যাচাই করা না
    # থাকলে ব্লক না করে শুধু একটা সতর্কতা যোগ করা হচ্ছে।
    if buyer_name not in CARTON_VERIFIED_BUYERS:
        warnings.append(
            f"⚠️ '{buyer_name}' buyer-এর Carton PDF ফরম্যাট এখনো নির্দিষ্টভাবে "
            f"যাচাই করা হয়নি — আউটপুট ভালোভাবে চেক করে নিন।"
        )

    # Force override ব্যবহার করে সত্যিই কোনো মিসম্যাচ বাইপাস করা হয়ে থাকলে,
    # অডিট-ট্রেইলের জন্য Excel-এর Warnings শীটে সেটা লিখে রাখা হচ্ছে —
    # যাতে পরে কেউ চেক করলে বুঝতে পারে কোথায় ম্যানুয়ালি ওভাররাইড করা হয়েছিল।
    if force_override:
        pdf_customer = header_info.get('customer', '')
        pdf_buyer = header_info.get('buyer', '')
        if pdf_customer and not values_match_ci(customer_name, pdf_customer):
            warnings.append(
                f"⚠️ FORCE OVERRIDE: Customer ম্যানুয়ালি '{customer_name}' বসানো হয়েছে, "
                f"কিন্তু PDF-এ ছিল '{pdf_customer}' — দয়া করে যাচাই করুন।"
            )
        if pdf_buyer and not values_match_ci(buyer_name, pdf_buyer):
            warnings.append(
                f"⚠️ FORCE OVERRIDE: Buyer ম্যানুয়ালি '{buyer_name}' বসানো হয়েছে, "
                f"কিন্তু PDF-এ ছিল '{pdf_buyer}' — দয়া করে যাচাই করুন।"
            )

    base_name = os.path.splitext(pdf_file.filename)[0]

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, f'{base_name}_Output.xlsx')
            build_combined_excel(
                line_items, header_info, out_path,
                profile=customer_type,
                customer_override=customer_name or None,
                buyer_override=buyer_name or None,
                po_override=po_number_override or None,
                delivery_date=delivery_date_final,
                delivery_address=delivery_address,
                raw_df=raw_df,
                summary_df=summary_df,
                warnings=warnings,
                remark_place=remark_place,
                remark_address=remark_address,
            )
            with open(out_path, 'rb') as f:
                file_bytes = f.read()
    except Exception as e:
        # Excel বানাতে গিয়ে কোনো সমস্যা হলে যেন কখনোই ভাঙা/অসম্পূর্ণ ফাইল
        # ডাউনলোড না হয়ে যায় — বরং সাফ একটা এরর মেসেজ দেখানো হয়
        return jsonify({'error': f'Excel ফাইল বানাতে সমস্যা হয়েছে: {str(e)}'}), 500

    if not file_bytes:
        return jsonify({'error': 'Excel ফাইল খালি তৈরি হয়েছে — আবার চেষ্টা করুন'}), 500

    buf = io.BytesIO(file_bytes)
    response = send_file(
        buf,
        as_attachment=True,
        download_name=f'{base_name}_Output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response.headers['Content-Length'] = str(len(file_bytes))
    response.headers['X-Warning-Count'] = str(len(warnings))
    return response


@app.route('/thermal/extract_header', methods=['POST'])
def thermal_extract_header():
    """Carton-এর /extract_header-এর মতোই — PDF আপলোড হওয়ার সাথে সাথেই
    PO Number/Customer/Buyer এবং Delivery Place/Address হিন্ট বের করে ফেরত দেয়।"""
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDF ফাইল পাওয়া যায়নি'}), 400

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({'error': 'ফাইল সিলেক্ট করা হয়নি'}), 400

    pdf_bytes_raw = pdf_file.read()
    try:
        header_info, line_items, raw_df, summary_df = process_pdf_thermal(io.BytesIO(pdf_bytes_raw))
    except Exception as e:
        return jsonify({'error': f'PDF থেকে তথ্য বের করতে সমস্যা হয়েছে: {str(e)}'}), 422

    header_info['buyer'] = resolve_alias(header_info.get('buyer', ''), THERMAL_BUYER_ALIASES)
    header_info['customer'] = resolve_alias(header_info.get('customer', ''), CUSTOMER_ALIASES)

    delivery_info = get_unique_delivery_info_thermal(raw_df)

    return jsonify({
        'po_number': header_info.get('po_number', '') or '',
        'customer': header_info.get('customer', '') or '',
        'buyer': header_info.get('buyer', '') or '',
        'delivery_places_pdf': delivery_info['delivery_places'],
        'delivery_addresses_pdf': delivery_info['delivery_addresses'],
    })


@app.route('/thermal/process', methods=['POST'])
def thermal_process():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDF ফাইল পাওয়া যায়নি'}), 400

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({'error': 'ফাইল সিলেক্ট করা হয়নি'}), 400

    customer_type = 'IN-HOUSE'  # Thermal মডিউলে আপাতত শুধু IN-HOUSE সাপোর্ট করা হচ্ছে
    customer_name = request.form.get('customer_name', '').strip()
    buyer_name = request.form.get('buyer_name', '').strip()
    po_number_override = request.form.get('po_number', '').strip()
    delivery_mode = request.form.get('delivery_mode', 'auto').strip()
    delivery_date_manual = request.form.get('delivery_date', '').strip()
    delivery_address = request.form.get('delivery_address', '').strip()
    measurement = request.form.get('measurement', '').strip()
    remark_place = request.form.get('remark_place', '').strip().lower() in ('1', 'true', 'on', 'yes')
    remark_address = request.form.get('remark_address', '').strip().lower() in ('1', 'true', 'on', 'yes')
    force_override = request.form.get('force_override', '').strip().lower() in ('1', 'true', 'on', 'yes')

    buyer_error = validate_buyer_in_list(buyer_name, THERMAL_BUYERS)
    if buyer_error:
        return jsonify({'error': buyer_error}), 422

    customer_error = validate_customer(customer_type, customer_name)
    if customer_error:
        return jsonify({'error': customer_error}), 422

    address_error = validate_delivery_address(customer_name, delivery_address)
    if address_error:
        return jsonify({'error': address_error}), 422

    if delivery_mode == 'manual':
        is_valid, err, parsed_date = validate_manual_delivery_date(delivery_date_manual)
        if not is_valid:
            return jsonify({'error': err}), 422
        delivery_date_final = format_delivery_date(parsed_date)
    else:
        delivery_date_final = format_delivery_date(get_default_delivery_date())

    pdf_bytes_raw = pdf_file.read()

    try:
        header_info, line_items, raw_df, summary_df = process_pdf_thermal(io.BytesIO(pdf_bytes_raw))
    except Exception as e:
        return jsonify({'error': f'PDF পড়তে সমস্যা হয়েছে: {str(e)}'}), 422

    if not line_items:
        return jsonify({'error': 'কোনো লাইন-আইটেম পাওয়া যায়নি এই PDF থেকে'}), 422

    header_info['buyer'] = resolve_alias(header_info.get('buyer', ''), THERMAL_BUYER_ALIASES)
    header_info['customer'] = resolve_alias(header_info.get('customer', ''), CUSTOMER_ALIASES)

    po_error = validate_po_number(po_number_override, header_info.get('po_number', ''))
    if po_error:
        return jsonify({'error': po_error}), 422

    customer_pdf_error = None if force_override else validate_matches_pdf(
        'Customer', customer_name, header_info.get('customer', ''))
    if customer_pdf_error:
        return jsonify({'error': customer_pdf_error}), 422

    buyer_pdf_error = None if force_override else validate_matches_pdf(
        'Buyer', buyer_name, header_info.get('buyer', ''))
    if buyer_pdf_error:
        return jsonify({'error': buyer_pdf_error}), 422

    warnings = validate_thermal_line_items(line_items)

    # buyer সিস্টেমে (মাস্টার লিস্টে) থাকলেই যথেষ্ট প্রসেসিং চালানোর জন্য —
    # কিন্তু এই buyer-এর Thermal PDF ফরম্যাট এখনো নির্দিষ্টভাবে যাচাই করা না
    # থাকলে ব্লক না করে শুধু একটা সতর্কতা যোগ করা হচ্ছে, যাতে ইউজার আউটপুট
    # ভালোভাবে চেক করে নিতে পারেন।
    if buyer_name not in THERMAL_VERIFIED_BUYERS:
        warnings.append(
            f"⚠️ '{buyer_name}' buyer-এর Thermal PDF ফরম্যাট এখনো নির্দিষ্টভাবে "
            f"যাচাই করা হয়নি — আউটপুট (বিশেষ করে সাইজ/কোয়ান্টিটি/রেফারেন্স) "
            f"ভালোভাবে চেক করে নিন।"
        )

    if force_override:
        pdf_customer = header_info.get('customer', '')
        pdf_buyer = header_info.get('buyer', '')
        if pdf_customer and not values_match_ci(customer_name, pdf_customer):
            warnings.append(
                f"⚠️ FORCE OVERRIDE: Customer ম্যানুয়ালি '{customer_name}' বসানো হয়েছে, "
                f"কিন্তু PDF-এ ছিল '{pdf_customer}' — দয়া করে যাচাই করুন।"
            )
        if pdf_buyer and not values_match_ci(buyer_name, pdf_buyer):
            warnings.append(
                f"⚠️ FORCE OVERRIDE: Buyer ম্যানুয়ালি '{buyer_name}' বসানো হয়েছে, "
                f"কিন্তু PDF-এ ছিল '{pdf_buyer}' — দয়া করে যাচাই করুন।"
            )

    if not measurement:
        warnings.append("Measurement ফাঁকা রাখা হয়েছে (ইউজার confirm করেছেন) — পরে ম্যানুয়ালি বসাতে হবে।")

    base_name = os.path.splitext(pdf_file.filename)[0]

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, f'{base_name}_Output.xlsx')
            build_thermal_excel(
                line_items, header_info, out_path,
                customer_override=customer_name or None,
                buyer_override=buyer_name or None,
                po_override=po_number_override or None,
                delivery_date=delivery_date_final,
                delivery_address=delivery_address,
                measurement=measurement,
                raw_df=raw_df,
                summary_df=summary_df,
                warnings=warnings,
                remark_place=remark_place,
                remark_address=remark_address,
            )
            with open(out_path, 'rb') as f:
                file_bytes = f.read()
    except Exception as e:
        return jsonify({'error': f'Excel ফাইল বানাতে সমস্যা হয়েছে: {str(e)}'}), 500

    if not file_bytes:
        return jsonify({'error': 'Excel ফাইল খালি তৈরি হয়েছে — আবার চেষ্টা করুন'}), 500

    buf = io.BytesIO(file_bytes)
    response = send_file(
        buf,
        as_attachment=True,
        download_name=f'{base_name}_Output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response.headers['Content-Length'] = str(len(file_bytes))
    response.headers['X-Warning-Count'] = str(len(warnings))
    return response


@app.route('/autocarton/process_outhouse_excel', methods=['POST'])
def autocarton_process_outhouse_excel():
    """আউট হাউজ Carton — একাধিক বুকিং এক্সেল (.xls/.xlsx) একসাথে আপলোড করে
    একটাই কম্বাইনড Excel টেমপ্লেট বানায়। Customer/Buyer/PO এখানে ম্যানুয়ালি
    ইনপুট দিতে হয় (এক্সেলে এসব হেডার-লেভেল তথ্য PDF-এর মতো পরিষ্কারভাবে
    থাকে না), শুধু লাইন-আইটেমগুলো ফাইল থেকে বের করে কম্বাইন করা হয়।"""
    files = request.files.getlist('files')
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({'error': 'অন্তত একটা এক্সেল ফাইল আপলোড করুন'}), 400

    customer_name = request.form.get('customer_name', '').strip()
    buyer_name = request.form.get('buyer_name', '').strip()
    po_number_override = request.form.get('po_number', '').strip()
    item_name_override = request.form.get('item_name', '').strip() or 'Master Carton'
    manual_ply = request.form.get('ply', '').strip()
    delivery_mode = request.form.get('delivery_mode', 'auto').strip()
    delivery_date_manual = request.form.get('delivery_date', '').strip()
    delivery_address = request.form.get('delivery_address', '').strip()

    customer_error = validate_customer('OUT-HOUSE', customer_name)
    if customer_error:
        return jsonify({'error': customer_error}), 422

    buyer_error = validate_buyer_in_list(buyer_name, BUYERS)
    if buyer_error:
        return jsonify({'error': buyer_error}), 422

    address_error = validate_delivery_address(customer_name, delivery_address)
    if address_error:
        return jsonify({'error': address_error}), 422

    if delivery_mode == 'manual':
        is_valid, err, parsed_date = validate_manual_delivery_date(delivery_date_manual)
        if not is_valid:
            return jsonify({'error': err}), 422
        delivery_date_final = format_delivery_date(parsed_date)
    else:
        delivery_date_final = format_delivery_date(get_default_delivery_date())

    file_tuples = [(io.BytesIO(f.read()), f.filename) for f in files]
    try:
        line_items, file_errors = combine_booking_excels(
            file_tuples, item_name_override=item_name_override, manual_ply=manual_ply)
    except Exception as e:
        return jsonify({'error': f'এক্সেল ফাইল পড়তে সমস্যা হয়েছে: {str(e)}'}), 422

    # .xls/.xlsx পড়ার জন্য দরকারি লাইব্রেরি (xlrd/calamine/openpyxl) কোনোটাই
    # ইনস্টল করা না থাকলে প্রতিটা ফাইলে একই এরর আসবে — কিন্তু এই হার্ড-ব্লক
    # শুধু তখনই দেখানো হবে যখন সত্যিই একটা ফাইলও প্রসেস করা যায়নি (not line_items)।
    # একটা ফাইলে সমস্যা হলেও বাকি ফাইলগুলো ঠিকভাবে প্রসেস হয়ে থাকলে, এখানে আটকানো
    # হবে না — সেই একটা ফাইলের এরর Warnings শীটে যোগ হয়ে বাকিটা স্বাভাবিকভাবে
    # এগিয়ে যাবে (আগে এই bug-এর কারণে একটা ফাইলে সমস্যা হলে পুরো ব্যাচ আটকে যেত)।
    if not line_items and file_errors and all('(লাইব্রেরি মিসিং)' in e for e in file_errors):
        return jsonify({
            'error': 'সার্ভারে .xls/.xlsx পড়ার জন্য দরকারি লাইব্রেরি (xlrd/python-calamine) '
                     'ইনস্টল করা নেই। Terminal-এ গিয়ে "pip install -r requirements.txt" '
                     'চালিয়ে সার্ভার আবার রিস্টার্ট করুন।'
        }), 422

    if not line_items:
        msg = 'কোনো লাইন-আইটেম পাওয়া যায়নি।'
        if file_errors:
            msg += ' সমস্যা: ' + '; '.join(file_errors)
        return jsonify({'error': msg}), 422

    warnings = validate_line_items(line_items)
    for e in file_errors:
        warnings.append(f"⚠️ এই ফাইলটা স্কিপ হয়েছে: {e}")

    if buyer_name not in CARTON_VERIFIED_BUYERS:
        warnings.append(
            f"⚠️ '{buyer_name}' buyer-এর OUT-HOUSE Excel ফরম্যাট এখনো নির্দিষ্টভাবে "
            f"যাচাই করা হয়নি — আউটপুট ভালোভাবে চেক করে নিন।"
        )

    header_info = {
        'po_number': po_number_override or '',
        'customer': customer_name,
        'buyer': buyer_name,
    }

    combined_label = '_'.join(sorted({str(it.get('po_no', '')) for it in line_items if it.get('po_no')}))[:60]
    base_name = f"{customer_name}_{buyer_name}_{combined_label}_OUTHOUSE".replace(' ', '_')

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, f'{base_name}_Output.xlsx')
            build_combined_excel(
                line_items, header_info, out_path, profile='OUT-HOUSE',
                customer_override=customer_name or None,
                buyer_override=buyer_name or None,
                po_override=po_number_override or None,
                delivery_date=delivery_date_final,
                delivery_address=delivery_address,
                warnings=warnings,
            )
            with open(out_path, 'rb') as f:
                file_bytes = f.read()
    except Exception as e:
        return jsonify({'error': f'Excel ফাইল বানাতে সমস্যা হয়েছে: {str(e)}'}), 500

    if not file_bytes:
        return jsonify({'error': 'Excel ফাইল খালি তৈরি হয়েছে — আবার চেষ্টা করুন'}), 500

    buf = io.BytesIO(file_bytes)
    response = send_file(
        buf,
        as_attachment=True,
        download_name=f'{base_name}_Output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response.headers['Content-Length'] = str(len(file_bytes))
    response.headers['X-Warning-Count'] = str(len(warnings))
    response.headers['X-File-Count'] = str(len(files))
    return response


@app.route('/autocarton/extract_header_outhouse_pdf', methods=['POST'])
def autocarton_extract_header_outhouse_pdf():
    """OUT-HOUSE PDF (Trims Booking ফরম্যাট) আপলোড হওয়ার সাথে সাথেই Booking No
    (-> PO Number), Buyer, Customer বের করে ফেরত দেয় — IN-HOUSE PDF ফ্লো-র
    /extract_header endpoint-এর মতোই, autofill-এর জন্য। Customer/Buyer আমাদের
    ফিক্সড লিস্টের সাথে fuzzy-ম্যাচ করে ক্যানোনিকাল নামে বসানো হয় (case বা
    ছোটখাটো বানান-ভিন্নতা সমস্যা করবে না)।"""
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDF ফাইল পাওয়া যায়নি'}), 400

    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({'error': 'ফাইল সিলেক্ট করা হয়নি'}), 400

    try:
        header_info, _items = process_trims_booking_pdf(
            io.BytesIO(pdf_file.read()), CUSTOMERS.get('OUT-HOUSE', []), BUYERS)
    except Exception as e:
        return jsonify({'error': f'PDF থেকে তথ্য বের করতে সমস্যা হয়েছে: {str(e)}'}), 422

    return jsonify({
        'po_number': header_info.get('po_number', '') or '',
        'customer': header_info.get('customer', '') or '',
        'buyer': header_info.get('buyer', '') or '',
    })


@app.route('/autocarton/process_outhouse_trims_booking_pdf', methods=['POST'])
def autocarton_process_outhouse_trims_booking_pdf():
    """আউট হাউজ Carton — 'Multiple Job Wise Trims Booking' PDF ফরম্যাট
    (যেমন Barnali Textile-এর বুকিং শিট)। এই ফরম্যাট IN-HOUSE/সাধারণ
    OUT-HOUSE PDF-এর থেকে সম্পূর্ণ ভিন্ন (EWO/Style/PONo টেবিল না, বরং
    প্রতিটা Job/Style-এর জন্য 'Size Sensitive'/'NO sensitive' নামে দুটো
    সাব-ব্লক) — তাই আলাদা এক্সট্র্যাক্টর ও রুট।

    Item Name ('Master Carton'/'Top Bottom') আর Ply (5/3) PDF থেকেই প্রতিটা
    রো-তে automatically ঠিক হয়ে যায় (Item Group অনুযায়ী) — তাই এখানে
    Excel-ফ্লো-র মতো ম্যানুয়াল dropdown লাগে না।
    """
    files = request.files.getlist('files')
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({'error': 'অন্তত একটা PDF ফাইল আপলোড করুন'}), 400

    customer_name = request.form.get('customer_name', '').strip()
    buyer_name = request.form.get('buyer_name', '').strip()
    po_number_override = request.form.get('po_number', '').strip()
    delivery_mode = request.form.get('delivery_mode', 'auto').strip()
    delivery_date_manual = request.form.get('delivery_date', '').strip()
    delivery_address = request.form.get('delivery_address', '').strip()
    primark_weight_class = request.form.get('primark_weight_class', '').strip()

    customer_error = validate_customer('OUT-HOUSE', customer_name)
    if customer_error:
        return jsonify({'error': customer_error}), 422

    buyer_error = validate_buyer_in_list(buyer_name, BUYERS)
    if buyer_error:
        return jsonify({'error': buyer_error}), 422

    # Primark-এর জন্য স্পেশাল রুল: সবসময় 3-ply, এবং ABOVE/BELOW 10KG
    # বাধ্যতামূলক সিলেক্ট করতে হবে (Style No-এর সাথে '/' দিয়ে জুড়ে বসবে)।
    # ফ্রন্টএন্ডেও এটা চেক করা হয়, কিন্তু ব্যাকএন্ডেও একই চেক রাখা হচ্ছে
    # (defense in depth — সরাসরি API কল করলেও যেন এড়ানো না যায়)।
    is_primark = buyer_name.strip().lower() == 'primark'
    if is_primark and primark_weight_class not in ('ABOVE 10KG', 'BELOW 10KG'):
        return jsonify({'error': "Primark buyer-এর জন্য 'ABOVE 10KG' বা 'BELOW 10KG' সিলেক্ট করা আবশ্যক।"}), 422

    address_error = validate_delivery_address(customer_name, delivery_address)
    if address_error:
        return jsonify({'error': address_error}), 422

    if delivery_mode == 'manual':
        is_valid, err, parsed_date = validate_manual_delivery_date(delivery_date_manual)
        if not is_valid:
            return jsonify({'error': err}), 422
        delivery_date_final = format_delivery_date(parsed_date)
    else:
        delivery_date_final = format_delivery_date(get_default_delivery_date())

    line_items = []
    file_errors = []
    for f in files:
        try:
            _hdr, items = process_trims_booking_pdf(io.BytesIO(f.read()), CUSTOMERS.get('OUT-HOUSE', []), BUYERS)
            if not items:
                file_errors.append(f"{f.filename}: কোনো লাইন-আইটেম পাওয়া যায়নি (পরিচিত ফরম্যাট না হতে পারে)")
                continue
            line_items.extend(items)
        except Exception as e:
            file_errors.append(f"{f.filename}: {str(e)}")

    if not line_items:
        msg = 'কোনো লাইন-আইটেম পাওয়া যায়নি।'
        if file_errors:
            msg += ' সমস্যা: ' + '; '.join(file_errors)
        return jsonify({'error': msg}), 422

    # Primark: সবসময় 3-ply (Item Group যা-ই হোক), আর Style No-এর সাথে
    # ইউজারের সিলেক্ট করা ABOVE/BELOW 10KG '/' দিয়ে জুড়ে বসবে
    # (যেমন Style '90627' -> '90627/ABOVE 10KG')।
    if is_primark:
        for item in line_items:
            item['ply'] = '3'
            if item.get('style_no'):
                item['style_no'] = f"{item['style_no']}/{primark_weight_class}"

    warnings = validate_line_items(line_items)
    for e in file_errors:
        warnings.append(f"⚠️ এই ফাইলটা স্কিপ হয়েছে: {e}")

    if buyer_name not in CARTON_VERIFIED_BUYERS:
        warnings.append(
            f"⚠️ '{buyer_name}' buyer-এর এই OUT-HOUSE PDF ফরম্যাট এখনো নির্দিষ্টভাবে "
            f"যাচাই করা হয়নি — আউটপুট ভালোভাবে চেক করে নিন।"
        )

    header_info = {
        'po_number': po_number_override or '',
        'customer': customer_name,
        'buyer': buyer_name,
    }

    combined_label = '_'.join(sorted({str(it.get('style_no', '')) for it in line_items if it.get('style_no')}))[:60]
    base_name = f"{customer_name}_{buyer_name}_{combined_label}_OUTHOUSE".replace(' ', '_')
    # ফাইলসিস্টেম-অসেইফ ক্যারেক্টার সরানো হচ্ছে (Primark-এর 'ABOVE 10KG' style
    # suffix-এ '/' থাকে, যেটা path separator হিসেবে ভুল বোঝার কারণে এরর দিচ্ছিল)
    base_name = re.sub(r'[\\/:*?"<>|]', '-', base_name)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, f'{base_name}_Output.xlsx')
            build_combined_excel(
                line_items, header_info, out_path, profile='OUT-HOUSE',
                customer_override=customer_name or None,
                buyer_override=buyer_name or None,
                po_override=po_number_override or None,
                delivery_date=delivery_date_final,
                delivery_address=delivery_address,
                warnings=warnings,
            )
            with open(out_path, 'rb') as f:
                file_bytes = f.read()
    except Exception as e:
        return jsonify({'error': f'Excel ফাইল বানাতে সমস্যা হয়েছে: {str(e)}'}), 500

    if not file_bytes:
        return jsonify({'error': 'Excel ফাইল খালি তৈরি হয়েছে — আবার চেষ্টা করুন'}), 500

    buf = io.BytesIO(file_bytes)
    response = send_file(
        buf,
        as_attachment=True,
        download_name=f'{base_name}_Output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response.headers['Content-Length'] = str(len(file_bytes))
    response.headers['X-Warning-Count'] = str(len(warnings))
    response.headers['X-File-Count'] = str(len(files))
    return response


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)