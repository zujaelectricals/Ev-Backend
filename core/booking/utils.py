"""
Utility functions for booking operations
"""
import hashlib
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from core.settings.models import PlatformSettings
from core.wallet.models import WalletTransaction
import os
import requests
import json
import logging

logger = logging.getLogger(__name__)


def generate_booking_receipt_pdf(booking, payment):
    """
    Generate a professional PDF payment receipt for a booking.
    Styled like a professional loan agreement document with:
    - DIGITALLY SIGNED badge + large title header
    - Amber/golden company info band
    - Customer Information section
    - Payment Details 4-column table
    - Declaration paragraph
    - Digital Signature Certificate (green box) with SHA-256 hash

    Args:
        booking: Booking instance
        payment: Payment instance (booking payment)

    Returns:
        ContentFile: PDF file content
    """
    # Get company information
    platform_settings = PlatformSettings.get_settings()
    company_name = platform_settings.company_name
    company_email = platform_settings.company_email
    company_phone = platform_settings.company_phone
    company_address = platform_settings.company_address

    # Create PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=0.55*inch, bottomMargin=0.55*inch,
        leftMargin=0.75*inch, rightMargin=0.75*inch
    )

    elements = []
    styles = getSampleStyleSheet()

    # ── Colour palette ──────────────────────────────────────────────────────────
    green_color  = colors.HexColor('#28a745')
    light_green  = colors.HexColor('#d4edda')
    dark_green   = colors.HexColor('#155724')
    amber_color  = colors.HexColor('#C8A84B')
    dark_header  = colors.HexColor('#1a1a2e')
    light_bg     = colors.HexColor('#f0f4f8')
    blue_val     = colors.HexColor('#1a6fc4')

    # Usable page width
    pw = A4[0] - 1.5*inch   # 6.77 inches

    # ── Helper paragraph styles ─────────────────────────────────────────────────
    def ps(name, **kw):
        base = kw.pop('parent', styles['Normal'])
        return ParagraphStyle(name, parent=base, **kw)

    section_style = ps('SecHead', parent=styles['Heading2'],
                       fontSize=13, textColor=colors.HexColor('#1a1a1a'),
                       fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=5)

    # ── 1. TOP HEADER ROW: "DIGITALLY SIGNED" badge  +  "PAYMENT RECEIPT" ──────
    badge_para = Paragraph(
        '&#x2726; DIGITALLY SIGNED',
        ps('BadgeTxt', fontSize=9, textColor=colors.white,
           fontName='Helvetica-Bold', alignment=TA_CENTER)
    )
    badge_cell = Table([[badge_para]], colWidths=[1.55*inch])
    badge_cell.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), green_color),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))

    title_para = Paragraph(
        'PAYMENT RECEIPT',
        ps('MainTitle', parent=styles['Heading1'],
           fontSize=26, textColor=colors.HexColor('#1a1a1a'),
           fontName='Helvetica-Bold', alignment=TA_RIGHT,
           spaceAfter=0, spaceBefore=0)
    )

    hdr_table = Table(
        [[badge_cell, title_para]],
        colWidths=[1.65*inch, pw - 1.65*inch]
    )
    hdr_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'BOTTOM'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(hdr_table)
    elements.append(Spacer(1, 0.07*inch))

    # ── 2. AMBER COMPANY BAND ───────────────────────────────────────────────────
    booking_date    = booking.confirmed_at or booking.created_at
    booking_date_str = f"{booking_date.day}/{booking_date.month}/{booking_date.year}"

    amber_data = [
        [Paragraph(f'<b>{company_name}</b>',
                   ps('CoName', fontSize=11, textColor=colors.HexColor('#1a1a1a'),
                      fontName='Helvetica-Bold', alignment=TA_CENTER))],
        [Paragraph(f'Document ID: {booking.booking_number}  |  Date: {booking_date_str}',
                   ps('DocId', fontSize=9, textColor=colors.HexColor('#1a1a1a'),
                      fontName='Helvetica', alignment=TA_CENTER))],
    ]
    amber_band = Table(amber_data, colWidths=[pw])
    amber_band.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), amber_color),
        ('TOPPADDING',    (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
    ]))
    elements.append(amber_band)
    elements.append(Spacer(1, 0.18*inch))

    # ── 3. CUSTOMER INFORMATION ─────────────────────────────────────────────────
    elements.append(Paragraph('CUSTOMER INFORMATION', section_style))

    user           = booking.user
    user_full_name = user.get_full_name() or user.username
    mobile         = getattr(user, 'mobile', None) or 'N/A'
    email          = user.email or 'N/A'

    def cell_para(label, value):
        return Paragraph(
            f'<b>{label}:</b>  {value}',
            ps(f'ci_{label}', fontSize=10, textColor=colors.HexColor('#333333'),
               fontName='Helvetica', leading=14)
        )

    cust_table = Table(
        [
            [cell_para('Full Name', user_full_name), cell_para('Booking No', booking.booking_number)],
            [cell_para('Mobile',    mobile),          cell_para('Email',      email)],
        ],
        colWidths=[pw/2, pw/2]
    )
    cust_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), light_bg),
        ('BOX',           (0,0), (-1,-1), 0.75, colors.HexColor('#c0c8d0')),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(cust_table)
    elements.append(Spacer(1, 0.18*inch))

    # ── 4. PAYMENT DETAILS ──────────────────────────────────────────────────────
    elements.append(Paragraph('PAYMENT DETAILS', section_style))

    vehicle          = booking.vehicle_model
    vehicle_name     = vehicle.name or 'Electric Vehicle'
    payment_date_str = (f"{payment.payment_date.day}/{payment.payment_date.month}/{payment.payment_date.year}"
                        if payment.payment_date else 'N/A')
    remaining        = float(booking.total_amount) - float(payment.amount)

    def th(text):
        return Paragraph(
            f'<b>{text}</b>',
            ps(f'th_{text}', fontSize=10, textColor=colors.white,
               fontName='Helvetica-Bold', alignment=TA_LEFT)
        )

    c1, c2, c3, c4 = pw*0.22, pw*0.28, pw*0.22, pw*0.28

    details_table = Table(
        [
            [th('Parameter'), th('Value'), th('Parameter'), th('Value')],
            ['Vehicle Model',    vehicle_name,
             'Total Amount',     Paragraph(f'Rs. {float(booking.total_amount):,.2f}',
                                           ps('va1', fontSize=10, textColor=blue_val, fontName='Helvetica'))],
            ['Vehicle Color',    booking.vehicle_color or 'N/A',
             'Amount Paid',      Paragraph(f'Rs. {float(payment.amount):,.2f}',
                                           ps('va2', fontSize=10, textColor=blue_val, fontName='Helvetica'))],
            ['Battery Variant',  booking.battery_variant or 'N/A',
             'Remaining Amt.',   Paragraph(f'Rs. {remaining:,.2f}',
                                           ps('va3', fontSize=10, textColor=blue_val, fontName='Helvetica'))],
            ['Booking Date',     booking_date_str,
             'Payment Method',   payment.payment_method.title()],
            ['Payment Date',     payment_date_str,
             'Transaction ID',   payment.transaction_id or 'N/A'],
        ],
        colWidths=[c1, c2, c3, c4]
    )
    details_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND',    (0,0), (-1,0), dark_header),
        ('TOPPADDING',    (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        # Data rows
        ('BACKGROUND',    (0,1), (-1,-1), colors.white),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f6f8fa')]),
        ('TEXTCOLOR',     (0,1), (-1,-1), colors.HexColor('#333333')),
        ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,1), (-1,-1), 10),
        ('GRID',          (0,0), (-1,-1), 0.4, colors.HexColor('#d0d0d0')),
        ('TOPPADDING',    (0,1), (-1,-1), 6),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 7),
        ('RIGHTPADDING',  (0,0), (-1,-1), 7),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 0.18*inch))

    # ── 5. DECLARATION ──────────────────────────────────────────────────────────
    elements.append(Paragraph('DECLARATION', section_style))

    decl_text = (
        f'I, <b>{user_full_name}</b>, hereby declare that I have read, understood, and agree to all '
        f'terms and conditions of this Booking Receipt, Privacy Policy, and Payment Agreement. '
        f'I confirm that all information provided is true and accurate. This receipt has been digitally '
        f'confirmed via Razorpay Payment Gateway as per the Information Technology Act, 2000 and '
        f'RBI Guidelines on Digital Payments.'
    )
    elements.append(Paragraph(decl_text,
                               ps('Decl', fontSize=9, textColor=colors.HexColor('#333333'),
                                  fontName='Helvetica', leading=14)))
    elements.append(Spacer(1, 0.22*inch))

    # ── 6. DIGITAL SIGNATURE CERTIFICATE ───────────────────────────────────────
    # Compute SHA-256 from key booking data
    hash_input = (
        f"{booking.booking_number}|{user_full_name}|"
        f"{payment.transaction_id}|{payment.amount}|"
        f"{booking_date.isoformat()}"
    )
    pdf_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    timestamp_str = timezone.now().strftime('%d %B %Y at %I:%M:%S %p IST')

    cert_heading_para = Paragraph(
        '&#x2726;  DIGITAL SIGNATURE CERTIFICATE',
        ps('CertHd', parent=styles['Heading2'],
           fontSize=12, textColor=dark_green,
           fontName='Helvetica-Bold', alignment=TA_CENTER,
           spaceBefore=0, spaceAfter=6)
    )

    def bullet(text, bold=False):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(
            f'&#x2022; {text}',
            ps(f'bl_{text[:8]}', fontSize=9, textColor=dark_green,
               fontName=fn, leading=14)
        )

    def right_item(text):
        return Paragraph(
            text,
            ps(f'ri_{text[:8]}', fontSize=9, textColor=dark_green,
               fontName='Helvetica', leading=14)
        )

    mobile_display = mobile if mobile != 'N/A' else 'N/A'
    cert_inner = Table(
        [
            [bullet(f'Signatory: {user_full_name}'),
             right_item(f'OTP Verified: &#x2726; (Mobile: {mobile_display})')],
            [bullet(f'Timestamp: {timestamp_str}'),
             right_item('Signing Method: OTP-Based eSign')],
            [bullet(f'IP Address: {getattr(booking, "ip_address", "N/A") or "N/A"}'),
             right_item('Compliance: IT Act 2000, RBI DSC Guidelines')],
        ],
        colWidths=[pw/2, pw/2]
    )
    cert_inner.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), light_green),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))

    hash_para = Paragraph(
        f'<b>SHA-256 Signature Hash:</b><br/>{pdf_hash}',
        ps('Hash', fontSize=8, textColor=dark_green,
           fontName='Courier', leading=11)
    )

    cert_outer = Table(
        [[cert_heading_para], [cert_inner], [hash_para]],
        colWidths=[pw]
    )
    cert_outer.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), light_green),
        ('BOX',           (0,0), (-1,-1), 2, green_color),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
    ]))

    elements.append(KeepTogether([cert_outer]))

    # ── Build PDF ────────────────────────────────────────────────────────────────
    doc.build(elements)
    pdf_content = buffer.getvalue()
    buffer.close()

    filename = f"receipt_{booking.booking_number}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content, name=filename)


def generate_payment_receipt_pdf(payment, razorpay_payment=None):
    """
    Generate a payment receipt PDF in the format of a rent payment receipt.
    Includes customer name, amount paid, platform fee, taxes, and payment date.
    
    Args:
        payment: Payment instance (booking payment from core.booking.models)
        razorpay_payment: Optional Razorpay Payment instance for gateway charges
    
    Returns:
        ContentFile: PDF file content
    """
    from core.booking.models import Payment as BookingPayment
    
    # Get company information
    company_address = "KUTTIYIDAYIL,ARRATTUVAZHY, Alappuzha North, Ambalapuzh A, Alappuzha- 688007"
    company_email = "zujaelectric@gmail.com"
    company_phone = "7356360777"
    
    # Get customer information
    user = payment.user
    customer_name = user.get_full_name() or user.username
    customer_address = f"{getattr(user, 'address_line1', '') or ''}, {getattr(user, 'city', '') or ''}, {getattr(user, 'state', '') or ''} {getattr(user, 'pincode', '') or ''}".strip(', ')
    if not customer_address or customer_address == ', ':
        customer_address = "N/A"
    customer_contact = getattr(user, 'mobile', '') or user.email or 'N/A'
    
    # Calculate amounts
    # payment.amount is the net amount (what gets credited to booking after gateway charges)
    net_amount = Decimal(str(payment.amount))
    
    # Get platform fee (gateway charges) from razorpay_payment if available
    platform_fee = Decimal('0.00')
    gross_amount = None
    
    # If razorpay_payment not provided, try to find it from transaction_id
    if not razorpay_payment and payment.payment_method == 'online' and payment.transaction_id:
        try:
            from core.payments.models import Payment as RazorpayPayment
            # Try to find by order_id (transaction_id is usually order_id)
            try:
                razorpay_payment = RazorpayPayment.objects.get(order_id=payment.transaction_id)
            except RazorpayPayment.DoesNotExist:
                # Try by payment_id if order_id doesn't match
                try:
                    razorpay_payment = RazorpayPayment.objects.get(payment_id=payment.transaction_id)
                except RazorpayPayment.DoesNotExist:
                    razorpay_payment = None
        except Exception as e:
            logger.warning(f"Could not find Razorpay payment for transaction_id {payment.transaction_id}: {e}")
            razorpay_payment = None
    
    if razorpay_payment:
        # Get gross amount (what user actually paid) from razorpay_payment
        # razorpay_payment.amount is the gross amount in paise (what user actually paid)
        gross_amount = Decimal(str(razorpay_payment.amount / 100))
        
        if razorpay_payment.gateway_charges is not None:
            # Use the gateway_charges from razorpay_payment (most accurate)
            platform_fee = Decimal(str(razorpay_payment.gateway_charges / 100))
        else:
            # If gateway_charges not set, calculate it as the difference between gross and net
            # Platform fee = gross_amount - net_amount (what user paid minus what gets credited)
            platform_fee = gross_amount - net_amount
            if platform_fee < 0:
                platform_fee = Decimal('0.00')
    elif payment.payment_method == 'online':
        # For online payments without razorpay_payment, calculate platform fee
        # Formula: gross = net / 0.9764, platform_fee = gross - net
        # RAZORPAY_NET_TO_GROSS_DIVISOR = 0.9764 (1 - 0.0236)
        RAZORPAY_NET_TO_GROSS_DIVISOR = Decimal('0.9764')
        gross_amount = net_amount / RAZORPAY_NET_TO_GROSS_DIVISOR
        # Round to 2 decimal places
        gross_amount = gross_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        platform_fee = gross_amount - net_amount
        if platform_fee < 0:
            platform_fee = Decimal('0.00')
    
    # Subtotal (net amount, what goes to booking)
    subtotal = net_amount
    
    # Total amount (what customer actually paid)
    # Always use gross_amount if available (most accurate - this is what user actually paid)
    # If gross_amount is not available, calculate as net_amount + platform_fee
    if gross_amount is not None:
        # Use gross_amount directly - this is the exact amount the user paid
        total_amount = gross_amount
    else:
        # For direct payments without razorpay, calculate total
        # If platform_fee exists, add it; otherwise total is just net_amount
        total_amount = net_amount + platform_fee
    
    # Calculate GST breakdown from platform_fee
    # Tax is included in platform fee (18% GST on 2% fee = 2.36% total)
    # GST on platform fee = platform_fee * (18/118) if we want to break it down
    gst_on_fee = platform_fee * Decimal('18') / Decimal('118') if platform_fee > 0 else Decimal('0.00')
    base_fee = platform_fee - gst_on_fee if platform_fee > 0 else Decimal('0.00')
    
    # Log for debugging
    logger.debug(
        f"Payment receipt calculation for payment {payment.id}: "
        f"net_amount={net_amount}, platform_fee={platform_fee}, "
        f"gross_amount={gross_amount}, total_amount={total_amount}, "
        f"subtotal={subtotal}, base_fee={base_fee}, gst_on_fee={gst_on_fee}"
    )
    
    # Payment date
    payment_date = payment.completed_at or payment.payment_date
    payment_date_str = payment_date.strftime('%B %d, %Y') if payment_date else timezone.now().strftime('%B %d, %Y')
    
    # Receipt ID
    if payment.transaction_id:
        # Use transaction_id if available, format as R-XXXXXXXX
        receipt_id = f"R-{str(payment.transaction_id)[-8:].zfill(8)}"
    else:
        # Use payment ID with zero padding
        receipt_id = f"R-{str(payment.id).zfill(8)}"
    
    # Create PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=0.3*inch, bottomMargin=0.5*inch,
        leftMargin=0.75*inch, rightMargin=0.75*inch
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Color palette
    gray_color = colors.HexColor('#808080')
    light_gray = colors.HexColor('#f5f5f5')
    dark_gray = colors.HexColor('#333333')
    black = colors.HexColor('#000000')
    
    # Usable page width
    pw = A4[0] - 1.5*inch
    
    # Helper function for paragraph styles
    def ps(name, **kw):
        base = kw.pop('parent', styles['Normal'])
        return ParagraphStyle(name, parent=base, **kw)
    
    # ── 1. HEADER WITH LOGO CENTERED AND ADDRESS BELOW ─────────────────────────────
    # Try to load logo
    logo_path = os.path.join(settings.BASE_DIR, 'Zuja_Logo-removebg-preview.png')
    logo_img = None
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=1.2*inch, height=1.2*inch)
        except Exception as e:
            logger.warning(f"Could not load logo image: {e}")
    
    # Logo centered at top
    if logo_img:
        logo_table = Table([[logo_img]], colWidths=[pw])
        logo_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(logo_table)
    else:
        # If no logo, create a placeholder
        logo_placeholder = Paragraph(
            '<b>ZUJA ELECTRICAL INNOVATION (P) LTD</b>',
            ps('LogoPlaceholder', fontSize=14, textColor=black, alignment=TA_CENTER,
               fontName='Helvetica-Bold')
        )
        logo_table = Table([[logo_placeholder]], colWidths=[pw])
        logo_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(logo_table)
    
    # Address below logo, centered
    address_para = Paragraph(
        company_address,
        ps('Address', fontSize=9, textColor=dark_gray, alignment=TA_CENTER,
           fontName='Helvetica')
    )
    address_table = Table([[address_para]], colWidths=[pw])
    address_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(address_table)
    
    # Contact info (Email and Phone) - centered below address
    contact_info = [
        Paragraph(f'<b>Email:</b> {company_email}', ps('Contact', fontSize=9, textColor=gray_color, alignment=TA_CENTER)),
        Paragraph(f'<b>Phone:</b> {company_phone}', ps('Contact', fontSize=9, textColor=gray_color, alignment=TA_CENTER)),
    ]
    contact_table = Table([[para] for para in contact_info], colWidths=[pw])
    contact_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(contact_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # ── 2. RECEIPT TITLE ──────────────────────────────────────────────────────────
    title = Paragraph(
        'Payment Receipt',
        ps('Title', fontSize=24, textColor=black, fontName='Helvetica-Bold',
           alignment=TA_CENTER, spaceAfter=15)
    )
    elements.append(title)
    elements.append(Spacer(1, 0.1*inch))
    
    # ── 3. RECEIPT DETAILS ────────────────────────────────────────────────────────
    receipt_details = Table([
        [Paragraph(f'<b>Receipt ID:</b> {receipt_id}', ps('Detail', fontSize=10)),
         Paragraph(f'<b>Date Issued:</b> {payment_date_str}', ps('Detail', fontSize=10))],
    ], colWidths=[pw/2, pw/2])
    receipt_details.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(receipt_details)
    elements.append(Spacer(1, 0.15*inch))
    
    # ── 4. TENANT/CUSTOMER INFORMATION ──────────────────────────────────────────────
    elements.append(Paragraph('Tenant Information:', ps('Section', fontSize=12, textColor=black,
                                                         fontName='Helvetica-Bold', spaceAfter=8)))
    
    tenant_info = Table([
        [Paragraph(f'<b>Name:</b> {customer_name}', ps('Info', fontSize=10))],
        [Paragraph(f'<b>Address:</b> {customer_address}', ps('Info', fontSize=10))],
        [Paragraph(f'<b>Contact:</b> {customer_contact}', ps('Info', fontSize=10))],
    ], colWidths=[pw])
    tenant_info.setStyle(TableStyle([
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(tenant_info)
    elements.append(Spacer(1, 0.2*inch))
    
    # ── 5. PAYMENT DETAILS TABLE ────────────────────────────────────────────────────
    elements.append(Paragraph('Payment Details', ps('Section', fontSize=12, textColor=black,
                                                    fontName='Helvetica-Bold', spaceAfter=8)))
    
    # Format currency (without symbol, just numbers)
    def format_currency(amount):
        return f"{amount:,.2f}"
    
    # Build payment table
    # Row 1: Payment amount (subtotal)
    payment_table_data = [
        ['Description', 'Subtotal', 'Tax', 'Total Amount'],
        [
            f'Payment for {payment_date.strftime("%B %Y") if payment_date else "Payment"}',
            format_currency(float(subtotal)),
            format_currency(0.00),
            format_currency(float(subtotal))
        ],
    ]
    
    # Row 2: Platform fee (if applicable)
    if platform_fee > 0:
        payment_table_data.append([
            'Platform Fee (Payment Gateway Charges)',
            format_currency(float(base_fee)),
            format_currency(float(gst_on_fee)),
            format_currency(float(platform_fee))
        ])
    
    # Row 3: Total - this should be the exact amount user paid (gross amount including platform fees)
    # The total should always be gross_amount (what user actually paid)
    # Use Paragraph objects for bold text instead of HTML tags
    total_desc = Paragraph('Total', ps('BoldText', fontSize=10, textColor=black, fontName='Helvetica-Bold'))
    total_amount_text = Paragraph(
        format_currency(float(total_amount)),
        ps('BoldText', fontSize=10, textColor=black, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    )
    # Total row: subtotal + base_fee in subtotal column, gst_on_fee in tax column, total_amount in total column
    payment_table_data.append([
        total_desc,
        format_currency(float(subtotal + base_fee)),
        format_currency(float(gst_on_fee)),
        total_amount_text
    ])
    
    payment_table = Table(payment_table_data, colWidths=[pw*0.5, pw*0.15, pw*0.15, pw*0.2])
    payment_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), light_gray),
        ('TEXTCOLOR', (0,0), (-1,0), black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (3,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('FONTSIZE', (0,1), (-1,-2), 9),
        ('FONTSIZE', (0,-1), (-1,-1), 10),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),  # Make last row bold
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,1), (-1,-1), 5),
        ('TOPPADDING', (0,1), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, gray_color),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(payment_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # ── 6. PAYMENT INFORMATION ─────────────────────────────────────────────────────
    elements.append(Paragraph('Payment Information:', ps('Section', fontSize=12, textColor=black,
                                                           fontName='Helvetica-Bold', spaceAfter=8)))
    
    payment_method = payment.get_payment_method_display() if hasattr(payment, 'get_payment_method_display') else 'Online'
    transaction_id = payment.transaction_id or 'N/A'
    
    payment_info = Table([
        [Paragraph(f'<b>Payment Method:</b> {payment_method}', ps('Info', fontSize=10))],
        [Paragraph(f'<b>Transaction ID:</b> {transaction_id}', ps('Info', fontSize=10))],
    ], colWidths=[pw])
    payment_info.setStyle(TableStyle([
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(payment_info)
    elements.append(Spacer(1, 0.2*inch))
    
    # ── 7. TERMS AND CONDITIONS ───────────────────────────────────────────────────
    elements.append(Paragraph('Terms and Conditions:', ps('Section', fontSize=12, textColor=black,
                                                           fontName='Helvetica-Bold', spaceAfter=8)))
    
    terms = [
        'I confirm that I am booking a vehicle as an individual, distributor, or customer ("Booker") with ZUJA Electrical Innovation Private Limited.',
        'I understand that booking a vehicle requires payment of a minimum booking / purchase order amount of ₹5,000, and a vehicle is considered booked only after the company receives this amount.',
        'I acknowledge that all amounts paid towards vehicle booking including booking amount, instalments, full payment, incentive adjustments, or any other mode of payment are strictly non-refundable.'
    ]
    
    terms_para = Paragraph(
        '<br/>'.join([f'{i+1}) {term}' for i, term in enumerate(terms)]),
        ps('Terms', fontSize=9, textColor=dark_gray, leading=14, alignment=TA_LEFT)
    )
    elements.append(terms_para)
    elements.append(Spacer(1, 0.2*inch))
    
    # ── 8. CLOSING MESSAGE ────────────────────────────────────────────────────────
    closing = Paragraph(
        'Thank you for your timely payment!',
        ps('Closing', fontSize=11, textColor=black, fontName='Helvetica-Bold',
           alignment=TA_CENTER, spaceBefore=10)
    )
    elements.append(closing)
    
    # ── BUILD PDF ─────────────────────────────────────────────────────────────────
    doc.build(elements)
    pdf_content = buffer.getvalue()
    buffer.close()
    
    filename = f"payment_receipt_{receipt_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content, name=filename)


def send_payment_receipt_email_msg91(payment):
    """
    Send payment receipt email via MSG91 API.
    
    Args:
        payment: Payment instance (must have receipt and user with email)
    
    Returns:
        tuple: (success: bool, error_message: str)
    """
    # Check if MSG91 is configured
    if not settings.MSG91_AUTH_KEY:
        logger.warning("MSG91_AUTH_KEY is not configured. Skipping payment receipt email.")
        return False, "MSG91 authentication key not configured"
    
    # Validate payment has required data
    if not payment.user or not payment.user.email:
        logger.warning(f"Payment {payment.id} has no user email. Skipping receipt email.")
        return False, "User email not found"
    
    if not payment.receipt:
        logger.warning(f"Payment {payment.id} has no receipt. Skipping receipt email.")
        return False, "Payment receipt not found"
    
    if payment.status != 'completed':
        logger.warning(f"Payment {payment.id} status is '{payment.status}', not 'completed'. Skipping receipt email.")
        return False, f"Payment status is '{payment.status}', not 'completed'"
    
    user_email = payment.user.email
    user_full_name = payment.user.get_full_name() or payment.user.username
    
    # Prepare email data
    # Format payment date (completed_at or payment_date as fallback)
    payment_date = payment.completed_at or payment.payment_date
    payment_date_str = payment_date.strftime('%d-%m-%Y') if payment_date else timezone.now().strftime('%d-%m-%Y')
    
    # Calculate expiry date (30 days after payment)
    expiry_date = payment_date + timedelta(days=30) if payment_date else timezone.now() + timedelta(days=30)
    expiry_date_str = expiry_date.strftime('%d-%m-%Y')
    
    # Generate absolute receipt URL
    receipt_url = payment.receipt.url
    
    # If URL is already absolute (e.g., Azure blob storage), use it as-is
    if receipt_url.startswith('http'):
        pass  # Already absolute
    else:
        # Construct absolute URL from MEDIA_URL
        if hasattr(settings, 'MEDIA_URL'):
            # Check if MEDIA_URL is absolute (e.g., Azure blob storage)
            if settings.MEDIA_URL.startswith('http'):
                # MEDIA_URL is already absolute, just append the relative path
                receipt_url = f"{settings.MEDIA_URL.rstrip('/')}/{receipt_url.lstrip('/')}"
            else:
                # MEDIA_URL is relative, need to construct full URL
                # Try to get base URL from settings or use a default
                base_url = getattr(settings, 'BASE_URL', None)
                if not base_url:
                    # Try to construct from ALLOWED_HOSTS or use localhost as fallback
                    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
                    if allowed_hosts and allowed_hosts[0] != '*':
                        protocol = 'https' if getattr(settings, 'USE_HTTPS', False) else 'http'
                        base_url = f"{protocol}://{allowed_hosts[0]}"
                    else:
                        # Last resort: use localhost (for development)
                        base_url = 'http://localhost:8000'
                
                # Construct full URL
                receipt_url = f"{base_url.rstrip('/')}{settings.MEDIA_URL.rstrip('/')}/{receipt_url.lstrip('/')}"
        else:
            # No MEDIA_URL setting, use receipt URL as-is (might fail, but better than nothing)
            logger.warning(f"MEDIA_URL not found in settings. Using receipt URL as-is: {receipt_url}")
    
    # Send email via MSG91
    try:
        url = "https://control.msg91.com/api/v5/email/send"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }
        
        payload = {
            "recipients": [
                {
                    "to": [
                        {
                            "email": user_email,
                            "name": user_full_name
                        }
                    ],
                    "variables": {
                        "params": {
                            "customer_name": user_full_name,
                            "booking_date": payment_date_str,
                            "expiry_date": expiry_date_str,
                            "receipt_url": receipt_url
                        }
                    }
                }
            ],
            "from": {
                "email": "no-reply@zujainnovations.com"
            },
            "domain": "zujainnovations.com",
            "template_id": "confirmation1"
        }
        
        logger.info(f"MSG91 Payment Receipt Email Request - Payment: {payment.id}, Email: {user_email}")
        logger.debug(f"MSG91 Payment Receipt Email Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        logger.info(f"MSG91 Payment Receipt Email Response - Payment: {payment.id}, Response: {json.dumps(data, indent=2)}")
        
        # Check if email was sent successfully
        if data.get("status") == "success" and data.get("hasError") == False:
            logger.info(f"Payment receipt email sent successfully for payment {payment.id}, email {user_email}")
            return True, None
        else:
            # Extract error message if available
            errors = data.get("errors", {})
            error_msg = str(errors) if errors else "Unknown error from MSG91"
            logger.warning(
                f"MSG91 payment receipt email failed for payment {payment.id}, email {user_email}: {error_msg}"
            )
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        logger.error(
            f"MSG91 payment receipt email network error for payment {payment.id}, email {user_email}: {error_msg}",
            exc_info=True
        )
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(
            f"MSG91 payment receipt email unexpected error for payment {payment.id}, email {user_email}: {error_msg}",
            exc_info=True
        )
        return False, error_msg


def send_booking_confirmation_email_msg91(booking):
    """
    Send booking confirmation email via MSG91 API.
    
    Args:
        booking: Booking instance (must have status='active' and payment_receipt)
    
    Returns:
        tuple: (success: bool, error_message: str)
    """
    # Check if MSG91 is configured
    if not settings.MSG91_AUTH_KEY:
        logger.warning("MSG91_AUTH_KEY is not configured. Skipping booking confirmation email.")
        return False, "MSG91 authentication key not configured"
    
    # Validate booking has required data
    if not booking.user or not booking.user.email:
        logger.warning(f"Booking {booking.id} has no user email. Skipping confirmation email.")
        return False, "User email not found"
    
    if not booking.payment_receipt:
        logger.warning(f"Booking {booking.id} has no payment receipt. Skipping confirmation email.")
        return False, "Payment receipt not found"
    
    if booking.status != 'active':
        logger.warning(f"Booking {booking.id} status is '{booking.status}', not 'active'. Skipping confirmation email.")
        return False, f"Booking status is '{booking.status}', not 'active'"
    
    user_email = booking.user.email
    user_full_name = booking.user.get_full_name() or booking.user.username
    
    # Prepare email data
    # Format booking date (confirmed_at or created_at as fallback)
    booking_date = booking.confirmed_at or booking.created_at
    booking_date_str = booking_date.strftime('%d-%m-%Y')
    
    # Calculate expiry date (30 days after booking confirmation)
    expiry_date = booking_date + timedelta(days=30)
    expiry_date_str = expiry_date.strftime('%d-%m-%Y')
    
    # Generate absolute receipt URL
    receipt_url = booking.payment_receipt.url
    
    # If URL is already absolute (e.g., Azure blob storage), use it as-is
    if receipt_url.startswith('http'):
        pass  # Already absolute
    else:
        # Construct absolute URL from MEDIA_URL
        if hasattr(settings, 'MEDIA_URL'):
            # Check if MEDIA_URL is absolute (e.g., Azure blob storage)
            if settings.MEDIA_URL.startswith('http'):
                # MEDIA_URL is already absolute, just append the relative path
                receipt_url = f"{settings.MEDIA_URL.rstrip('/')}/{receipt_url.lstrip('/')}"
            else:
                # MEDIA_URL is relative, need to construct full URL
                # Try to get base URL from settings or use a default
                base_url = getattr(settings, 'BASE_URL', None)
                if not base_url:
                    # Try to construct from ALLOWED_HOSTS or use localhost as fallback
                    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
                    if allowed_hosts and allowed_hosts[0] != '*':
                        protocol = 'https' if getattr(settings, 'USE_HTTPS', False) else 'http'
                        base_url = f"{protocol}://{allowed_hosts[0]}"
                    else:
                        # Last resort: use localhost (for development)
                        base_url = 'http://localhost:8000'
                
                # Construct full URL
                receipt_url = f"{base_url.rstrip('/')}{settings.MEDIA_URL.rstrip('/')}/{receipt_url.lstrip('/')}"
        else:
            # No MEDIA_URL setting, use receipt URL as-is (might fail, but better than nothing)
            logger.warning(f"MEDIA_URL not found in settings. Using receipt URL as-is: {receipt_url}")
    
    # Send email via MSG91
    try:
        url = "https://control.msg91.com/api/v5/email/send"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }
        
        payload = {
            "recipients": [
                {
                    "to": [
                        {
                            "email": user_email,
                            "name": user_full_name
                        }
                    ],
                    "variables": {
                        "params": {
                            "customer_name": user_full_name,
                            "booking_date": booking_date_str,
                            "expiry_date": expiry_date_str,
                            "receipt_url": receipt_url
                        }
                    }
                }
            ],
            "from": {
                "email": "no-reply@zujainnovations.com"
            },
            "domain": "zujainnovations.com",
            "template_id": "confirmation1"
        }
        
        logger.info(f"MSG91 Booking Confirmation Email Request - Booking: {booking.id}, Email: {user_email}")
        logger.debug(f"MSG91 Booking Confirmation Email Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        logger.info(f"MSG91 Booking Confirmation Email Response - Booking: {booking.id}, Response: {json.dumps(data, indent=2)}")
        
        # Check if email was sent successfully
        if data.get("status") == "success" and data.get("hasError") == False:
            logger.info(f"Booking confirmation email sent successfully for booking {booking.id}, email {user_email}")
            return True, None
        else:
            # Extract error message if available
            errors = data.get("errors", {})
            error_msg = str(errors) if errors else "Unknown error from MSG91"
            logger.warning(
                f"MSG91 booking confirmation email failed for booking {booking.id}, email {user_email}: {error_msg}"
            )
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        logger.error(
            f"MSG91 booking confirmation email network error for booking {booking.id}, email {user_email}: {error_msg}",
            exc_info=True
        )
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(
            f"MSG91 booking confirmation email unexpected error for booking {booking.id}, email {user_email}: {error_msg}",
            exc_info=True
        )
        return False, error_msg


def process_active_buyer_bonus(user, booking):
    """
    Process active buyer bonus: Add ₹5000 to user's Total paid when they become an active buyer.
    
    This bonus is given to all Active buyers who have paid >= activation_amount.
    This bonus reduces the remaining balance on the booking.
    
    Args:
        user: User instance who just became an active buyer
        booking: Booking instance that triggered the active buyer status (latest booking)
    
    Returns:
        bool: True if bonus was applied, False otherwise (already given, not qualified, or error)
    """
    from core.booking.models import Booking
    
    try:
        # Get platform settings
        platform_settings = PlatformSettings.get_settings()
        activation_amount = platform_settings.activation_amount
        
        # Check if bonus was already given (prevent duplicates)
        if WalletTransaction.objects.filter(
            user=user,
            transaction_type='ACTIVE_BUYER_BONUS'
        ).exists():
            logger.info(
                f"Active buyer bonus already given to user {user.username}. Skipping."
            )
            return False
        
        # Verify user is an Active Buyer (actual payments >= activation_amount)
        # Check ACTUAL PAYMENTS, not bookings.total_paid (which might include bonus)
        # This prevents circular dependency
        from core.booking.models import Payment
        actual_payments_total = Payment.objects.filter(
            booking__user=user,
            booking__status__in=['active', 'completed'],
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        if actual_payments_total < activation_amount:
            logger.info(
                f"User {user.username} does not qualify for active buyer bonus. "
                f"Actual payments: {actual_payments_total}, Activation amount: {activation_amount}"
            )
            return False
        
        # Apply bonus: debit ₹5000 from remaining_balance (NOT added to total_paid)
        bonus_amount = Decimal('5000.00')

        with transaction.atomic():
            # Lock booking to prevent concurrent updates
            booking = Booking.objects.select_for_update().get(pk=booking.pk)

            # Record the bonus as a separate deduction – total_paid is untouched
            booking.bonus_applied = bonus_amount
            # remaining_amount = total_amount - total_paid - bonus_applied (recalculated in save())

            # Update booking status if fully paid after bonus deduction
            projected_remaining = booking.total_amount - booking.total_paid - bonus_amount
            if projected_remaining <= 0:
                booking.status = 'completed'
                if not booking.completed_at:
                    booking.completed_at = timezone.now()

            booking.save()

            # Create wallet transaction record for audit trail
            # Note: This is NOT a wallet credit, just a record of the bonus being applied to booking
            from core.wallet.utils import get_or_create_wallet
            wallet = get_or_create_wallet(user)

            WalletTransaction.objects.create(
                user=user,
                wallet=wallet,
                transaction_type='ACTIVE_BUYER_BONUS',
                amount=bonus_amount,
                balance_before=wallet.balance,  # Wallet balance unchanged
                balance_after=wallet.balance,   # Wallet balance unchanged
                description=(
                    f"Active buyer bonus: ₹{bonus_amount} debited from remaining balance "
                    f"of booking {booking.booking_number}"
                ),
                reference_id=booking.id,
                reference_type='booking'
            )

            logger.info(
                f"Active buyer bonus applied to user {user.username}: "
                f"₹{bonus_amount} debited from remaining balance of booking {booking.booking_number}. "
                f"total_paid: ₹{booking.total_paid}, bonus_applied: ₹{booking.bonus_applied}, "
                f"remaining_amount: ₹{booking.remaining_amount}"
            )
        
        return True
        
    except Exception as e:
        logger.error(
            f"Error processing active buyer bonus for user {user.username}, booking {booking.id}: {e}",
            exc_info=True
        )
        return False

