"""
Utility functions for booking operations
"""
import hashlib
from io import BytesIO
from decimal import Decimal
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

