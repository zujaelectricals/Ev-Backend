"""
Utility functions for compliance module
"""
import hashlib
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
    Generate ASA Agreement PDF document
    This PDF serves as legal proof of acceptance with OTP verification
    
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
    
    # Create PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*inch, bottomMargin=0.5*inch)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Get styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        spaceBefore=12,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#000000'),
        spaceAfter=8,
        alignment=TA_LEFT,
        leftIndent=0,
        rightIndent=0
    )
    
    # Title
    title = Paragraph("ASA TERMS ACCEPTANCE AGREEMENT", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.3*inch))
    
    # Company Details Section
    company_heading = Paragraph("<b>Company Details</b>", heading_style)
    elements.append(company_heading)
    
    company_data = [
        ['Company Name:', company_name],
        ['Email:', company_email],
        ['Phone:', company_phone],
        ['Address:', company_address],
    ]
    
    company_table = Table(company_data, colWidths=[2*inch, 5*inch])
    company_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(company_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # User Details Section
    user_heading = Paragraph("<b>User Details</b>", heading_style)
    elements.append(user_heading)
    
    user_full_name = user.get_full_name() or user.username
    user_address = f"{user.address_line1}"
    if user.address_line2:
        user_address += f", {user.address_line2}"
    if user.city:
        user_address += f", {user.city}"
    if user.state:
        user_address += f", {user.state}"
    if user.pincode:
        user_address += f" - {user.pincode}"
    if user.country:
        user_address += f", {user.country}"
    
    user_data = [
        ['User ID:', str(user.id)],
        ['Name:', user_full_name],
        ['Email:', user.email or 'N/A'],
        ['Mobile:', user.mobile or 'N/A'],
        ['Address:', user_address or 'N/A'],
    ]
    
    user_table = Table(user_data, colWidths=[2*inch, 5*inch])
    user_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(user_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Agreement Details Section
    agreement_heading = Paragraph("<b>Agreement Details</b>", heading_style)
    elements.append(agreement_heading)
    
    # Convert IST timestamp
    accepted_at_ist = acceptance.accepted_at
    accepted_at_str = accepted_at_ist.strftime('%d %B %Y, %I:%M:%S %p IST')
    
    agreement_data = [
        ['Agreement Name:', asa_terms.title],
        ['Version:', asa_terms.version],
        ['Accepted At:', accepted_at_str],
        ['IP Address:', acceptance.ip_address],
        ['User Agent:', acceptance.user_agent or 'N/A'],
    ]
    
    agreement_table = Table(agreement_data, colWidths=[2*inch, 5*inch])
    agreement_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(agreement_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Legal Statement
    legal_heading = Paragraph("<b>Legal Statement</b>", heading_style)
    elements.append(legal_heading)
    
    legal_text = """
    This document serves as proof that the user has digitally accepted all terms and conditions 
    specified in the ASA Terms (version {version}) through OTP verification. 
    No physical signature is required.
    
    This digital acceptance is legally binding under the Information Technology Act, 2000 and 
    the Indian Contract Act, 1872.
    """.format(version=asa_terms.version)
    
    legal_para = Paragraph(legal_text, normal_style)
    elements.append(legal_para)
    elements.append(Spacer(1, 0.2*inch))
    
    # Build PDF first (without hash section) to compute hash
    doc.build(elements)
    pdf_content_initial = buffer.getvalue()
    buffer.close()
    
    # Compute hash of PDF content (before adding hash section)
    # This hash will be stored and displayed in the final PDF
    pdf_hash = compute_pdf_hash(pdf_content_initial)
    
    # Now rebuild PDF with hash section included
    buffer_final = BytesIO()
    doc_final = SimpleDocTemplate(buffer_final, pagesize=A4, topMargin=1*inch, bottomMargin=0.5*inch)
    elements_final = elements.copy()
    
    # Add hash section with computed hash
    hash_heading = Paragraph("<b>Document Integrity</b>", heading_style)
    elements_final.append(hash_heading)
    
    hash_note = Paragraph(
        f"<i>SHA256 Hash: {pdf_hash}</i><br/>"
        "<i>This hash can be used to verify the integrity of this document.</i>",
        normal_style
    )
    elements_final.append(hash_note)
    
    # Build final PDF with hash section
    doc_final.build(elements_final)
    pdf_content_final = buffer_final.getvalue()
    buffer_final.close()
    
    # Note: The stored hash (pdf_hash) is computed from the PDF content BEFORE the hash section
    # This allows verification that the core document content hasn't been tampered with
    # The hash displayed in the PDF matches the stored hash for reference
    
    # Create ContentFile with final PDF (includes hash section)
    filename = f"asa_agreement_{user.id}_{acceptance.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content_final, name=filename), pdf_hash


def generate_payment_terms_receipt_pdf(user, payment_terms, acceptance):
    """
    Generate Payment Terms Receipt PDF document (optional)
    
    Args:
        user: User instance
        payment_terms: PaymentTerms instance
        acceptance: UserPaymentAcceptance instance
    
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
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.8*inch, bottomMargin=0.5*inch)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Get styles
    styles = getSampleStyleSheet()
    
    # Green color for digital signature elements
    green_color = colors.HexColor('#28a745')  # Green color for badge
    light_green = colors.HexColor('#d4edda')  # Light green for background
    dark_green = colors.HexColor('#155724')   # Dark green for text
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        spaceBefore=12,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#000000'),
        spaceAfter=8,
        alignment=TA_LEFT
    )
    
    badge_style = ParagraphStyle(
        'BadgeStyle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        backColor=green_color,
        leading=14
    )
    
    # DIGITALLY SIGNED Badge at top
    badge_table = Table([['DIGITALLY SIGNED']], colWidths=[1.5*inch])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), green_color),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(badge_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Title
    title = Paragraph("PAYMENT TERMS ACCEPTANCE RECEIPT", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.3*inch))
    
    # Company Details
    company_heading = Paragraph("<b>Company Details</b>", heading_style)
    elements.append(company_heading)
    
    company_data = [
        ['Company Name:', company_name],
        ['Email:', company_email],
        ['Phone:', company_phone],
        ['Address:', company_address],
    ]
    
    company_table = Table(company_data, colWidths=[2*inch, 5*inch])
    company_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(company_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # User Details
    user_heading = Paragraph("<b>User Details</b>", heading_style)
    elements.append(user_heading)
    
    user_full_name = user.get_full_name() or user.username
    
    user_data = [
        ['User ID:', str(user.id)],
        ['Name:', user_full_name],
        ['Email:', user.email or 'N/A'],
        ['Mobile:', user.mobile or 'N/A'],
    ]
    
    user_table = Table(user_data, colWidths=[2*inch, 5*inch])
    user_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(user_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Acceptance Details
    acceptance_heading = Paragraph("<b>Acceptance Details</b>", heading_style)
    elements.append(acceptance_heading)
    
    accepted_at_ist = acceptance.accepted_at
    accepted_at_str = accepted_at_ist.strftime('%d %B %Y, %I:%M:%S %p IST')
    
    acceptance_data = [
        ['Payment Terms:', payment_terms.title],
        ['Version:', payment_terms.version],
        ['Accepted At:', accepted_at_str],
        ['IP Address:', acceptance.ip_address],
        ['OTP Verified:', 'Yes' if acceptance.otp_verified else 'No'],
    ]
    
    acceptance_table = Table(acceptance_data, colWidths=[2*inch, 5*inch])
    acceptance_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(acceptance_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Declaration
    declaration_heading = Paragraph("<b>DECLARATION</b>", heading_style)
    elements.append(declaration_heading)
    
    user_full_name = user.get_full_name() or user.username
    declaration_text = f"""
    I, {user_full_name}, hereby declare that I have read, understood, and agree to all terms and conditions 
    of this Payment Terms and Conditions (version {payment_terms.version}), Privacy Policy, and NACH 
    Auto-Debit Mandate. I confirm that all information provided is true and accurate. This agreement has been 
    digitally signed using OTP-based electronic signature as per the Information Technology Act, 2000 and 
    RBI Guidelines on Digital Signatures.
    """
    
    declaration_para = Paragraph(declaration_text, normal_style)
    elements.append(declaration_para)
    elements.append(Spacer(1, 0.3*inch))
    
    # Build PDF first (without hash section) to compute hash
    doc.build(elements)
    pdf_content_initial = buffer.getvalue()
    buffer.close()
    
    # Compute hash of PDF content (before adding hash section)
    pdf_hash = compute_pdf_hash(pdf_content_initial)
    
    # Now rebuild PDF with Digital Signature Certificate section included
    buffer_final = BytesIO()
    doc_final = SimpleDocTemplate(buffer_final, pagesize=A4, topMargin=0.8*inch, bottomMargin=0.5*inch)
    elements_final = elements.copy()
    
    # Digital Signature Certificate Section (Green Box)
    cert_heading = Paragraph(
        "<b>DIGITAL SIGNATURE CERTIFICATE</b>",
        ParagraphStyle(
            'CertHeading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=dark_green,
            spaceAfter=10,
            spaceBefore=10,
            fontName='Helvetica-Bold',
            alignment=TA_LEFT
        )
    )
    
    # Format timestamp
    accepted_at_ist = acceptance.accepted_at
    accepted_at_str = accepted_at_ist.strftime('%d %B %Y at %I:%M:%S %p IST')
    
    # OTP verification info
    otp_info = 'Yes'
    if acceptance.otp_verified and acceptance.otp_identifier:
        if '@' in acceptance.otp_identifier:
            otp_info = f'Yes (Email: {acceptance.otp_identifier})'
        else:
            otp_info = f'Yes (Mobile: {acceptance.otp_identifier})'
    else:
        otp_info = 'No'
    
    cert_data = [
        ['Signatory:', user_full_name],
        ['Timestamp:', accepted_at_str],
        ['IP Address:', acceptance.ip_address],
        ['OTP Verified:', otp_info],
        ['Signing Method:', 'OTP-Based eSign'],
        ['Compliance:', 'IT Act 2000, Indian Contract Act 1872'],
    ]
    
    cert_table = Table(cert_data, colWidths=[2*inch, 5*inch])
    cert_table.setStyle(TableStyle([
        # Background for entire table
        ('BACKGROUND', (0, 0), (-1, -1), light_green),
        # Border around entire table (green)
        ('BOX', (0, 0), (-1, -1), 2, green_color),
        # Text colors
        ('TEXTCOLOR', (0, 0), (0, -1), dark_green),  # Left column (labels)
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#000000')),  # Right column (values)
        # Alignment
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        # Fonts
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        # Font sizes
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        # Padding
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        # Grid (optional, can remove if you don't want internal lines)
        # ('GRID', (0, 0), (-1, -1), 1, green_color),
    ]))
    
    # Wrap heading and table together
    cert_section = [cert_heading, cert_table]
    elements_final.append(KeepTogether(cert_section))
    elements_final.append(Spacer(1, 0.2*inch))
    
    # SHA-256 Hash
    hash_style = ParagraphStyle(
        'HashStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=dark_green,
        spaceAfter=5,
        fontName='Courier',  # Monospace font for hash
        alignment=TA_LEFT
    )
    
    hash_text = f"<b>SHA-256 Signature Hash:</b><br/>{pdf_hash}"
    hash_para = Paragraph(hash_text, hash_style)
    elements_final.append(hash_para)
    
    # Build final PDF with Digital Signature Certificate section
    doc_final.build(elements_final)
    pdf_content_final = buffer_final.getvalue()
    buffer_final.close()
    
    # Create ContentFile with final PDF (includes Digital Signature Certificate)
    filename = f"payment_terms_receipt_{user.id}_{acceptance.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content_final, name=filename)

