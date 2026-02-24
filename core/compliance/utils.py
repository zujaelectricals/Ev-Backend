"""
Utility functions for compliance module
"""
import hashlib
import re
from io import BytesIO
from django.core.files.base import ContentFile
from django.utils import timezone
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
from core.users.models import User
from core.settings.models import PlatformSettings


def get_client_ip(request):
    """
    Extract client IP address from request
    Handles both direct connections and reverse proxy setups (Nginx, load balancers, etc.)
    
    Priority order:
    1. HTTP_X_REAL_IP - Set by Nginx (most reliable in reverse proxy setups)
    2. HTTP_X_FORWARDED_FOR - Standard header for proxied requests (first IP in chain)
    3. REMOTE_ADDR - Direct connection IP (fallback)
    
    Returns: IP address string or 'unknown' if none found
    """
    # First, try X-Real-IP (set by Nginx in reverse proxy setups)
    ip_address = request.META.get('HTTP_X_REAL_IP', '').strip()
    
    if not ip_address:
        # Try X-Forwarded-For (standard header for proxied requests)
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs in a chain (client, proxy1, proxy2, ...)
            # Take the first one (original client IP)
            ip_address = forwarded_for.split(',')[0].strip()
    
    if not ip_address:
        # Fallback to REMOTE_ADDR (direct connection)
        ip_address = request.META.get('REMOTE_ADDR', '').strip()
    
    # Validate IP address format (basic check)
    if ip_address and (ip_address == 'unknown' or not ip_address):
        return 'unknown'
    
    return ip_address or 'unknown'


def create_user_info_snapshot(user):
    """
    Create a snapshot of user information at a specific point in time
    This is stored for legal compliance and audit purposes
    """
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'mobile': user.mobile,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'is_distributor': user.is_distributor,
        'is_active_buyer': user.is_active_buyer,
        'date_joined': user.date_joined.isoformat() if user.date_joined else None,
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'address': {
            'address_line1': user.address_line1,
            'address_line2': user.address_line2,
            'city': user.city,
            'state': user.state,
            'pincode': user.pincode,
            'country': user.country,
        }
    }


def create_timeline_data(user, document, ip_address, user_agent=None):
    """
    Create timeline data for document acceptance
    Includes metadata about the acceptance event
    """
    return {
        'event_type': 'document_acceptance',
        'document_id': document.id,
        'document_title': document.title,
        'document_version': document.version,
        'document_type': document.document_type,
        'user_id': user.id,
        'user_username': user.username,
        'ip_address': ip_address,
        'user_agent': user_agent,
        'acceptance_method': 'otp_verified',
    }


def compute_pdf_hash(pdf_content):
    """
    Compute SHA256 hash of PDF content for integrity verification
    
    Args:
        pdf_content: bytes - PDF file content
    
    Returns:
        str: SHA256 hash in hexadecimal format (64 characters)
    """
    return hashlib.sha256(pdf_content).hexdigest()


def generate_asa_agreement_pdf(user, asa_terms, acceptance):
    """
    Generate ASA Agreement PDF document.
    Styled like a professional loan agreement document with:
    - DIGITALLY SIGNED badge + large title header
    - Amber/golden company info band
    - Signatory Information section
    - Acceptance Details 4-column table
    - Declaration paragraph
    - Digital Signature Certificate (green box) with SHA-256 hash

    Args:
        user: User instance
        asa_terms: AsaTerms instance
        acceptance: UserAsaAcceptance instance

    Returns:
        tuple: (ContentFile, str) - PDF file and SHA256 hash
    """
    # Get company information
    platform_settings = PlatformSettings.get_settings()
    company_name = platform_settings.company_name
    company_email = platform_settings.company_email
    company_phone = platform_settings.company_phone
    company_address = platform_settings.company_address

    # ── Colour palette ───────────────────────────────────────────────────────────
    green_color = colors.HexColor('#28a745')
    light_green = colors.HexColor('#d4edda')
    dark_green  = colors.HexColor('#155724')
    amber_color = colors.HexColor('#C8A84B')
    dark_header = colors.HexColor('#1a1a2e')
    light_bg    = colors.HexColor('#f0f4f8')
    blue_val    = colors.HexColor('#1a6fc4')

    # Build initial elements (for hash computation)
    def _build_elements(pdf_hash=None):
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=0.55*inch, bottomMargin=0.55*inch,
            leftMargin=0.75*inch, rightMargin=0.75*inch
        )
        elements = []
        styles = getSampleStyleSheet()

        # Usable page width
        pw = A4[0] - 1.5*inch  # ~6.77 inches

        # Helper: create a ParagraphStyle on the fly
        def ps(name, **kw):
            base = kw.pop('parent', styles['Normal'])
            return ParagraphStyle(name, parent=base, **kw)

        section_style = ps('SecHead', parent=styles['Heading2'],
                           fontSize=13, textColor=colors.HexColor('#1a1a1a'),
                           fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=5)

        # ── 1. TOP HEADER ────────────────────────────────────────────────────────
        title_para = Paragraph(
            'ASA TERMS ACCEPTANCE',
            ps('MainTitle', parent=styles['Heading1'],
               fontSize=18, textColor=colors.HexColor('#1a1a1a'),
               fontName='Helvetica-Bold', alignment=TA_CENTER,
               spaceAfter=8, spaceBefore=0)
        )
        elements.append(title_para)
        elements.append(Spacer(1, 0.12*inch))

        # ── 2. AMBER COMPANY BAND ────────────────────────────────────────────────
        accepted_at = acceptance.accepted_at
        accepted_date_str = f"{accepted_at.day}/{accepted_at.month}/{accepted_at.year}"

        amber_data = [
            [Paragraph(f'<b>{company_name}</b>',
                       ps('CoName', fontSize=11, textColor=colors.HexColor('#1a1a1a'),
                          fontName='Helvetica-Bold', alignment=TA_CENTER))],
            [Paragraph(
                f'Document ID: {asa_terms.version}  |  Date: {accepted_date_str}',
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

        # ── 3. SIGNATORY INFORMATION ─────────────────────────────────────────────
        elements.append(Paragraph('SIGNATORY INFORMATION', section_style))

        user_full_name = user.get_full_name() or user.username
        mobile = getattr(user, 'mobile', None) or 'N/A'
        email  = user.email or 'N/A'

        def cell_para(label, value):
            return Paragraph(
                f'<b>{label}:</b>  {value}',
                ps(f'ci_{label}', fontSize=10, textColor=colors.HexColor('#333333'),
                   fontName='Helvetica', leading=14)
            )

        cust_table = Table(
            [
                [cell_para('Full Name', user_full_name), cell_para('Mobile', mobile)],
                [cell_para('Email', email), ''],
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

        # ── 4. ACCEPTANCE DETAILS TABLE ──────────────────────────────────────────
        elements.append(Paragraph('ACCEPTANCE DETAILS', section_style))

        accepted_at_str = accepted_at.strftime('%d %B %Y')

        # OTP info
        otp_info = 'Yes'
        if acceptance.otp_verified and acceptance.otp_identifier:
            otp_info = (f'Yes (Email: {acceptance.otp_identifier})'
                        if '@' in acceptance.otp_identifier
                        else f'Yes (Mobile: {acceptance.otp_identifier})')
        elif not acceptance.otp_verified:
            otp_info = 'No'

        def th(text):
            return Paragraph(
                f'<b>{text}</b>',
                ps(f'th_{text[:6]}', fontSize=10, textColor=colors.white,
                   fontName='Helvetica-Bold', alignment=TA_LEFT)
            )

        c1, c2, c3, c4 = pw*0.22, pw*0.28, pw*0.22, pw*0.28

        def td(text, color=None):
            return Paragraph(
                str(text),
                ps(f'td_{str(text)[:6]}', fontSize=10, 
                   textColor=color or colors.HexColor('#333333'),
                   fontName='Helvetica', alignment=TA_LEFT)
            )

        details_table = Table(
            [
                [th('Parameter'), th('Value'), th('Parameter'), th('Value')],
                [td('Terms Title'),   td(asa_terms.title),
                 td('Version'),       td(asa_terms.version)],
                [td('Accepted At'),   td(accepted_at_str),
                 td('IP Address'),    td(acceptance.ip_address or 'N/A')],
                [td('OTP Verified'),  td(otp_info, blue_val),
                 td('Signing Method'), td('OTP-Based eSign')],
                [td('Compliance'),    td('IT Act 2000'),
                 td('RBI Guidelines'), td('DSC Guidelines')],
            ],
            colWidths=[c1, c2, c3, c4]
        )
        details_table.setStyle(TableStyle([
            ('BACKGROUND',     (0,0), (-1,0), dark_header),
            ('TOPPADDING',     (0,0), (-1,0), 8),
            ('BOTTOMPADDING',  (0,0), (-1,0), 8),
            ('BACKGROUND',     (0,1), (-1,-1), colors.white),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f6f8fa')]),
            ('TEXTCOLOR',      (0,1), (-1,-1), colors.HexColor('#333333')),
            ('FONTNAME',       (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',       (0,1), (-1,-1), 10),
            ('GRID',           (0,0), (-1,-1), 0.4, colors.HexColor('#d0d0d0')),
            ('TOPPADDING',     (0,1), (-1,-1), 6),
            ('BOTTOMPADDING',  (0,1), (-1,-1), 6),
            ('LEFTPADDING',    (0,0), (-1,-1), 7),
            ('RIGHTPADDING',   (0,0), (-1,-1), 7),
            ('VALIGN',         (0,0), (-1,-1), 'MIDDLE'),
            ('VALIGN',         (0,1), (-1,-1), 'MIDDLE'),
            ('ALIGN',          (0,0), (-1,-1), 'LEFT'),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.18*inch))

        # ── 5. DECLARATION ───────────────────────────────────────────────────────
        elements.append(Paragraph('DECLARATION', section_style))

        decl_text = (
            f'I, <b>{user_full_name}</b>, hereby declare that I have read, understood, and agree to all '
            f'terms and conditions of this ASA Terms and Conditions (version {asa_terms.version}), '
            f'Privacy Policy, and ASA terms. I confirm that all informations are correct. This agreement '
            f'has been digitally signed using OTP and confirmed by me.'
        )
        elements.append(Paragraph(
            decl_text,
            ps('Decl', fontSize=9, textColor=colors.HexColor('#333333'),
               fontName='Helvetica', leading=14)
        ))
        elements.append(Spacer(1, 0.22*inch))

        # ── 6. DIGITAL SIGNATURE CERTIFICATE (only in final pass) ───────────────
        if pdf_hash is not None:
            timestamp_str = accepted_at.strftime('%d %B %Y')

            cert_heading_para = Paragraph(
                '&#x2726;  DIGITAL SIGNATURE CERTIFICATE',
                ps('CertHd', parent=styles['Heading2'],
                   fontSize=12, textColor=dark_green,
                   fontName='Helvetica-Bold', alignment=TA_CENTER,
                   spaceBefore=0, spaceAfter=6)
            )

            def bullet(text):
                return Paragraph(
                    f'&#x2022; {text}',
                    ps(f'bl_{text[:8]}', fontSize=9, textColor=dark_green,
                       fontName='Helvetica', leading=14)
                )

            def right_item(text):
                return Paragraph(
                    text,
                    ps(f'ri_{text[:8]}', fontSize=9, textColor=dark_green,
                       fontName='Helvetica', leading=14)
                )

            cert_inner = Table(
                [
                    [bullet(f'Signatory: {user_full_name}'),
                     right_item(f'OTP Verified: &#x2726; ({otp_info})')],
                    [bullet(f'Timestamp: {timestamp_str}'),
                     right_item('Signing Method: OTP-Based eSign')],
                    [bullet(f'IP Address: {acceptance.ip_address or "N/A"}'),
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
                ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN',         (0,0), (0,-1), 'LEFT'),
                ('ALIGN',         (1,0), (1,-1), 'LEFT'),
            ]))

            hash_para = Paragraph(
                f'<b>SHA-256 Signature Hash:</b><br/>{pdf_hash}',
                ps('Hash', fontSize=8, textColor=dark_green,
                   fontName='Courier', leading=11)
            )

            # Wrap heading in a table cell to ensure proper background
            heading_cell = Table([[cert_heading_para]], colWidths=[pw])
            heading_cell.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('TOPPADDING',    (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LEFTPADDING',   (0,0), (-1,-1), 10),
                ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ]))
            
            # Wrap hash in a table cell
            hash_cell = Table([[hash_para]], colWidths=[pw])
            hash_cell.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('TOPPADDING',    (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING',   (0,0), (-1,-1), 10),
                ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ]))
            
            cert_outer = Table(
                [[heading_cell], [cert_inner], [hash_cell]],
                colWidths=[pw]
            )
            cert_outer.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('BOX',           (0,0), (-1,-1), 2, green_color),
                ('TOPPADDING',    (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('LEFTPADDING',   (0,0), (-1,-1), 0),
                ('RIGHTPADDING',  (0,0), (-1,-1), 0),
                ('VALIGN',        (0,0), (-1,-1), 'TOP'),
            ]))
            elements.append(KeepTogether([cert_outer]))

        doc.build(elements)
        return buffer

    # ── Pass 1: build without DSC to compute hash ───────────────────────────────
    buf1 = _build_elements(pdf_hash=None)
    pdf_hash = compute_pdf_hash(buf1.getvalue())
    buf1.close()

    # ── Pass 2: rebuild with DSC + hash ─────────────────────────────────────────
    buf2 = _build_elements(pdf_hash=pdf_hash)
    pdf_content = buf2.getvalue()
    buf2.close()

    filename = f"asa_agreement_{user.id}_{acceptance.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content, name=filename), pdf_hash


def generate_payment_terms_receipt_pdf(user, payment_terms, acceptance):
    """
    Generate Payment Terms Acceptance PDF document.
    Styled like a professional loan agreement document with:
    - DIGITALLY SIGNED badge + large title header
    - Amber/golden company info band
    - Signatory Information section
    - Acceptance Details 4-column table
    - Declaration paragraph
    - Digital Signature Certificate (green box) with SHA-256 hash

    Args:
        user: User instance
        payment_terms: PaymentTerms instance
        acceptance: UserPaymentAcceptance instance

    Returns:
        ContentFile: PDF file content
    """
    # Get company information
    platform_settings = PlatformSettings.get_settings()
    company_name = "ZUJA INNOVATION PVT LTD"  # Override for this document
    company_email = platform_settings.company_email
    company_phone = platform_settings.company_phone
    company_address = platform_settings.company_address

    # ── Colour palette ───────────────────────────────────────────────────────────
    green_color = colors.HexColor('#28a745')
    light_green = colors.HexColor('#d4edda')
    dark_green  = colors.HexColor('#155724')
    amber_color = colors.HexColor('#C8A84B')
    dark_header = colors.HexColor('#1a1a2e')
    light_bg    = colors.HexColor('#f0f4f8')
    blue_val    = colors.HexColor('#1a6fc4')

    # Build initial elements (for hash computation)
    def _build_elements(pdf_hash=None):
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=0.55*inch, bottomMargin=0.55*inch,
            leftMargin=0.75*inch, rightMargin=0.75*inch
        )
        elements = []
        styles = getSampleStyleSheet()

        # Usable page width
        pw = A4[0] - 1.5*inch  # ~6.77 inches

        # Helper: create a ParagraphStyle on the fly
        def ps(name, **kw):
            base = kw.pop('parent', styles['Normal'])
            return ParagraphStyle(name, parent=base, **kw)

        section_style = ps('SecHead', parent=styles['Heading2'],
                           fontSize=13, textColor=colors.HexColor('#1a1a1a'),
                           fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=5)

        # ── 1. TOP HEADER ────────────────────────────────────────────────────────
        title_para = Paragraph(
            'PAYMENT TERMS ACCEPTANCE',
            ps('MainTitle', parent=styles['Heading1'],
               fontSize=18, textColor=colors.HexColor('#1a1a1a'),
               fontName='Helvetica-Bold', alignment=TA_CENTER,
               spaceAfter=8, spaceBefore=0)
        )
        elements.append(title_para)
        elements.append(Spacer(1, 0.12*inch))

        # ── 2. AMBER COMPANY BAND ────────────────────────────────────────────────
        accepted_at = acceptance.accepted_at
        accepted_date_str = f"{accepted_at.day}/{accepted_at.month}/{accepted_at.year}"

        amber_data = [
            [Paragraph(f'<b>{company_name}</b>',
                       ps('CoName', fontSize=11, textColor=colors.HexColor('#1a1a1a'),
                          fontName='Helvetica-Bold', alignment=TA_CENTER))],
            [Paragraph(
                f'Document ID: {payment_terms.version}  |  Date: {accepted_date_str}',
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

        # ── 3. SIGNATORY INFORMATION ─────────────────────────────────────────────
        elements.append(Paragraph('SIGNATORY INFORMATION', section_style))

        user_full_name = user.get_full_name() or user.username
        mobile = getattr(user, 'mobile', None) or 'N/A'
        email  = user.email or 'N/A'

        def cell_para(label, value):
            return Paragraph(
                f'<b>{label}:</b>  {value}',
                ps(f'ci_{label}', fontSize=10, textColor=colors.HexColor('#333333'),
                   fontName='Helvetica', leading=14)
            )

        cust_table = Table(
            [
                [cell_para('Full Name', user_full_name), cell_para('Mobile', mobile)],
                [cell_para('Email', email), ''],
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

        # ── 4. ACCEPTANCE DETAILS TABLE ──────────────────────────────────────────
        elements.append(Paragraph('ACCEPTANCE DETAILS', section_style))

        accepted_at_str = accepted_at.strftime('%d %B %Y')

        # OTP info
        otp_info = 'Yes'
        if acceptance.otp_verified and acceptance.otp_identifier:
            otp_info = (f'Yes (Email: {acceptance.otp_identifier})'
                        if '@' in acceptance.otp_identifier
                        else f'Yes (Mobile: {acceptance.otp_identifier})')
        elif not acceptance.otp_verified:
            otp_info = 'No'

        def th(text):
            return Paragraph(
                f'<b>{text}</b>',
                ps(f'th_{text[:6]}', fontSize=10, textColor=colors.white,
                   fontName='Helvetica-Bold', alignment=TA_LEFT)
            )

        c1, c2, c3, c4 = pw*0.22, pw*0.28, pw*0.22, pw*0.28

        def td(text, color=None):
            return Paragraph(
                str(text),
                ps(f'td_{str(text)[:6]}', fontSize=10, 
                   textColor=color or colors.HexColor('#333333'),
                   fontName='Helvetica', alignment=TA_LEFT)
            )

        details_table = Table(
            [
                [th('Parameter'), th('Value'), th('Parameter'), th('Value')],
                [td('Terms Title'),   td(payment_terms.title),
                 td('Version'),       td(payment_terms.version)],
                [td('Accepted At'),   td(accepted_at_str),
                 td('IP Address'),    td(acceptance.ip_address or 'N/A')],
                [td('OTP Verified'),  td(otp_info, blue_val),
                 td('Signing Method'), td('OTP-Based eSign')],
                [td('Compliance'),    td('IT Act 2000'),
                 td('RBI Guidelines'), td('DSC Guidelines')],
            ],
            colWidths=[c1, c2, c3, c4]
        )
        details_table.setStyle(TableStyle([
            ('BACKGROUND',     (0,0), (-1,0), dark_header),
            ('TOPPADDING',     (0,0), (-1,0), 8),
            ('BOTTOMPADDING',  (0,0), (-1,0), 8),
            ('BACKGROUND',     (0,1), (-1,-1), colors.white),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f6f8fa')]),
            ('TEXTCOLOR',      (0,1), (-1,-1), colors.HexColor('#333333')),
            ('FONTNAME',       (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',       (0,1), (-1,-1), 10),
            ('GRID',           (0,0), (-1,-1), 0.4, colors.HexColor('#d0d0d0')),
            ('TOPPADDING',     (0,1), (-1,-1), 6),
            ('BOTTOMPADDING',  (0,1), (-1,-1), 6),
            ('LEFTPADDING',    (0,0), (-1,-1), 7),
            ('RIGHTPADDING',   (0,0), (-1,-1), 7),
            ('VALIGN',         (0,0), (-1,-1), 'MIDDLE'),
            ('VALIGN',         (0,1), (-1,-1), 'MIDDLE'),
            ('ALIGN',          (0,0), (-1,-1), 'LEFT'),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.18*inch))

        # ── 5. DECLARATION ───────────────────────────────────────────────────────
        elements.append(Paragraph('DECLARATION', section_style))

        decl_text = (
            f'I, <b>{user_full_name}</b>, hereby declare that I have read, understood, and agree to all '
            f'terms and conditions of this Payment Terms and Conditions (version {payment_terms.version}), '
            f'Privacy Policy, and payment terms. I confirm that all informations are correct. This agreement '
            f'has been digitally signed using OTP and confirmed by me.'
        )
        elements.append(Paragraph(
            decl_text,
            ps('Decl', fontSize=9, textColor=colors.HexColor('#333333'),
               fontName='Helvetica', leading=14)
        ))
        elements.append(Spacer(1, 0.22*inch))

        # ── 6. DIGITAL SIGNATURE CERTIFICATE (only in final pass) ───────────────
        if pdf_hash is not None:
            timestamp_str = accepted_at.strftime('%d %B %Y')

            cert_heading_para = Paragraph(
                '&#x2726;  DIGITAL SIGNATURE CERTIFICATE',
                ps('CertHd', parent=styles['Heading2'],
                   fontSize=12, textColor=dark_green,
                   fontName='Helvetica-Bold', alignment=TA_CENTER,
                   spaceBefore=0, spaceAfter=6)
            )

            def bullet(text):
                return Paragraph(
                    f'&#x2022; {text}',
                    ps(f'bl_{text[:8]}', fontSize=9, textColor=dark_green,
                       fontName='Helvetica', leading=14)
                )

            def right_item(text):
                return Paragraph(
                    text,
                    ps(f'ri_{text[:8]}', fontSize=9, textColor=dark_green,
                       fontName='Helvetica', leading=14)
                )

            cert_inner = Table(
                [
                    [bullet(f'Signatory: {user_full_name}'),
                     right_item(f'OTP Verified: &#x2726; ({otp_info})')],
                    [bullet(f'Timestamp: {timestamp_str}'),
                     right_item('Signing Method: OTP-Based eSign')],
                    [bullet(f'IP Address: {acceptance.ip_address or "N/A"}'),
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
                ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN',         (0,0), (0,-1), 'LEFT'),
                ('ALIGN',         (1,0), (1,-1), 'LEFT'),
            ]))

            hash_para = Paragraph(
                f'<b>SHA-256 Signature Hash:</b><br/>{pdf_hash}',
                ps('Hash', fontSize=8, textColor=dark_green,
                   fontName='Courier', leading=11)
            )

            # Wrap heading in a table cell to ensure proper background
            heading_cell = Table([[cert_heading_para]], colWidths=[pw])
            heading_cell.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('TOPPADDING',    (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LEFTPADDING',   (0,0), (-1,-1), 10),
                ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ]))
            
            # Wrap hash in a table cell
            hash_cell = Table([[hash_para]], colWidths=[pw])
            hash_cell.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('TOPPADDING',    (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING',   (0,0), (-1,-1), 10),
                ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ]))
            
            cert_outer = Table(
                [[heading_cell], [cert_inner], [hash_cell]],
                colWidths=[pw]
            )
            cert_outer.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), light_green),
                ('BOX',           (0,0), (-1,-1), 2, green_color),
                ('TOPPADDING',    (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('LEFTPADDING',   (0,0), (-1,-1), 0),
                ('RIGHTPADDING',  (0,0), (-1,-1), 0),
                ('VALIGN',        (0,0), (-1,-1), 'TOP'),
            ]))
            elements.append(KeepTogether([cert_outer]))

        doc.build(elements)
        return buffer

    # ── Pass 1: build without DSC to compute hash ───────────────────────────────
    buf1 = _build_elements(pdf_hash=None)
    pdf_hash = compute_pdf_hash(buf1.getvalue())
    buf1.close()

    # ── Pass 2: rebuild with DSC + hash ─────────────────────────────────────────
    buf2 = _build_elements(pdf_hash=pdf_hash)
    pdf_content = buf2.getvalue()
    buf2.close()

    filename = f"payment_terms_receipt_{user.id}_{acceptance.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content, name=filename)

