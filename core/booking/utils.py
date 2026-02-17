"""
Utility functions for booking operations
"""
from io import BytesIO
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from core.settings.models import PlatformSettings
import os


def generate_booking_receipt_pdf(booking, payment):
    """
    Generate a professional PDF payment receipt for a booking.
    
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
    # Increased top margin to accommodate header with logo and address
    # Ensure enough space so title doesn't overlap with content
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2.3*inch, bottomMargin=0.5*inch)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Get styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=8,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#333333'),
        fontName='Helvetica'
    )
    
    small_style = ParagraphStyle(
        'CustomSmall',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        fontName='Helvetica'
    )
    
    # Create a custom header with logo centered and company info
    def draw_header(canvas_obj, doc):
        """Draw custom header with logo centered and company information"""
        canvas_obj.saveState()
        # Calculate header position (from top of page)
        header_height = 2.0 * inch
        page_height = doc.height + doc.topMargin + doc.bottomMargin
        page_width = doc.width + doc.leftMargin + doc.rightMargin
        
        # Draw dark blue background (full width) - main header bar
        canvas_obj.setFillColor(colors.HexColor('#1a3a5c'))
        canvas_obj.rect(0, page_height - header_height, page_width, header_height, fill=1, stroke=0)
        
        # Draw teal wave pattern (simplified as gradient rectangles) - decorative wave
        wave_height = 0.4 * inch
        canvas_obj.setFillColor(colors.HexColor('#2d9cdb'))
        canvas_obj.rect(0, page_height - wave_height, page_width, wave_height, fill=1, stroke=0)
        
        # Draw lighter teal wave - top accent
        accent_height = 0.15 * inch
        canvas_obj.setFillColor(colors.HexColor('#4db8e8'))
        canvas_obj.rect(0, page_height - accent_height, page_width, accent_height, fill=1, stroke=0)
        
        # Logo area (top center)
        logo_size = 1.2 * inch
        logo_x = (page_width - logo_size) / 2
        logo_y = page_height - 0.3*inch - logo_size
        
        # Add company logo (top center) - check multiple possible locations
        logo_paths = [
            os.path.join(settings.BASE_DIR, 'Zuja_Logo-removebg-preview.png'),
            os.path.join(settings.BASE_DIR, 'static', 'images', 'Zuja_Logo-removebg-preview.png'),
            os.path.join(settings.BASE_DIR, 'static', 'Zuja_Logo-removebg-preview.png'),
            os.path.join(settings.MEDIA_ROOT, 'Zuja_Logo-removebg-preview.png') if hasattr(settings, 'MEDIA_ROOT') else None,
            # Fallback to old logo if new one not found
            os.path.join(settings.BASE_DIR, 'Zuja_Logo.jpeg'),
        ]
        logo_found = False
        for logo_path in logo_paths:
            if logo_path and os.path.exists(logo_path):
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(logo_path)
                    # Convert to RGB if needed
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    # Draw logo centered at top
                    canvas_obj.drawImage(logo_path, logo_x, logo_y, 
                                       width=logo_size, height=logo_size, preserveAspectRatio=True, mask='auto')
                    logo_found = True
                    break
                except Exception as e:
                    # If logo loading fails, continue without logo
                    pass
        
        # Company address below logo (centered, 75% width)
        address_y = logo_y - 0.25*inch
        address_width = page_width * 0.75
        address_x = (page_width - address_width) / 2
        
        # Draw address in a box or as centered text
        canvas_obj.setFillColor(colors.white)
        canvas_obj.setFont('Helvetica', 9)
        
        # Split address into lines if needed (wrap text)
        address_text = company_address
        # Try to split at commas for better formatting
        address_parts = address_text.split(', ')
        max_chars_per_line = 60  # Approximate characters per line for 75% width
        
        # Build address lines
        address_lines = []
        current_line = ""
        for part in address_parts:
            if len(current_line) + len(part) + 2 <= max_chars_per_line:
                if current_line:
                    current_line += ", " + part
                else:
                    current_line = part
            else:
                if current_line:
                    address_lines.append(current_line)
                current_line = part
        if current_line:
            address_lines.append(current_line)
        
        # Draw address lines (centered)
        line_height = 0.14*inch
        for i, line in enumerate(address_lines):
            text_width = canvas_obj.stringWidth(line, 'Helvetica', 9)
            text_x = (page_width - text_width) / 2
            canvas_obj.drawString(text_x, address_y - (i * line_height), line)
        
        # Contact info (email and phone) - right side, below address
        contact_y = address_y - (len(address_lines) * line_height) - 0.15*inch
        canvas_obj.setFont('Helvetica', 8)
        text_x = page_width - 0.2*inch
        
        # Email
        canvas_obj.drawRightString(text_x, contact_y, company_email)
        # Phone
        canvas_obj.drawRightString(text_x, contact_y - 0.12*inch, company_phone)
        
        # Title "Payment Receipt" - positioned below contact info, centered
        # Position title below the phone number (lowest contact element)
        phone_y = contact_y - 0.12*inch
        canvas_obj.setFont('Helvetica-Bold', 18)
        title_text = "Payment Receipt"
        title_width = canvas_obj.stringWidth(title_text, 'Helvetica-Bold', 18)
        title_x = (page_width - title_width) / 2
        # Position title with proper spacing below contact info
        title_y = phone_y - 0.3*inch
        
        # Draw white background rectangle behind title for visibility on dark blue header
        title_padding = 0.1*inch
        title_bg_height = 0.28*inch
        canvas_obj.setFillColor(colors.white)
        canvas_obj.rect(title_x - title_padding, title_y - 0.06*inch, 
                      title_width + (2 * title_padding), title_bg_height, 
                      fill=1, stroke=0)
        
        # Draw title text in black
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(title_x, title_y, title_text)
        
        canvas_obj.restoreState()
    
    # Title is now in the header, so we don't need it here
    # Add some spacing after header to prevent overlap with title
    elements.append(Spacer(1, 0.30*inch))
    
    # Date and Receipt Number - centered and styled
    receipt_date = timezone.now().strftime('%B %d, %Y')
    receipt_number = booking.booking_number
    date_receipt_style = ParagraphStyle(
        'DateReceiptStyle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
        alignment=TA_CENTER,
        fontName='Helvetica'
    )
    date_receipt_text = f"Date: {receipt_date} | Receipt Number: {receipt_number}"
    date_receipt_para = Paragraph(date_receipt_text, date_receipt_style)
    elements.append(date_receipt_para)
    elements.append(Spacer(1, 0.25*inch))
    
    # Billing Information
    user = booking.user
    billing_data = [
        ['Bill To:', 'Address:', 'Email:'],
        [
            f"{user.get_full_name() or user.username}",
            f"{user.address_line1 or ''} {user.address_line2 or ''}\n{user.city or ''}, {user.state or ''} {user.pincode or ''}".strip(),
            user.email or ''
        ]
    ]
    billing_table = Table(billing_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    billing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d0d0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
    ]))
    elements.append(billing_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Itemized Details
    vehicle = booking.vehicle_model
    vehicle_description = f"{vehicle.name or 'Electric Vehicle'} - {booking.vehicle_color or 'N/A'} - {booking.battery_variant}"
    
    # Calculate amounts (no tax)
    subtotal = float(payment.amount)
    total_amount = subtotal
    
    items_data = [
        ['Description', 'Quantity', 'Unit Price', 'Total'],
        [
            vehicle_description,
            '1',
            f"Rs. {subtotal:,.2f}",
            f"Rs. {subtotal:,.2f}"
        ]
    ]
    
    items_table = Table(items_data, colWidths=[3.5*inch, 1.2*inch, 1.5*inch, 1.3*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d0d0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # Summary - styled box
    summary_data = [
        ['', f"Total Amount: Rs. {total_amount:,.2f}"]
    ]
    summary_table = Table(summary_data, colWidths=[5.5*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -2), 11),
        ('TEXTCOLOR', (0, 0), (-1, -2), colors.HexColor('#333333')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 14),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#1a3a5c')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEABOVE', (0, -1), (-1, -1), 1.5, colors.HexColor('#1a3a5c')),
        ('TOPPADDING', (0, -1), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Payment Method - styled box
    payment_method_data = [
        ['Payment Method:', ''],
        ['Card Type:', payment.payment_method.title()],
        ['Transaction ID:', payment.transaction_id or 'N/A'],
        ['Transaction Date:', payment.payment_date.strftime('%B %d, %Y') if payment.payment_date else 'N/A']
    ]
    payment_method_table = Table(payment_method_data, colWidths=[2.5*inch, 5*inch])
    payment_method_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.HexColor('#666666')),
        ('TEXTCOLOR', (1, 1), (-1, -1), colors.HexColor('#333333')),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d0d0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
    ]))
    elements.append(payment_method_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Terms & Conditions - styled section
    terms_heading = Paragraph("Terms & Conditions:", heading_style)
    elements.append(terms_heading)
    
    # Terms in a styled box
    terms_text_style = ParagraphStyle(
        'TermsTextStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#333333'),
        fontName='Helvetica',
        leading=11,
        leftIndent=12,
        rightIndent=12,
        spaceAfter=8,
    )
    
    terms_text = """
    <b>1. Booking Amount Requirement:</b><br/>
    Booking a vehicle requires payment of a Purchase Order / Booking Amount. The minimum booking amount shall be Rs. 5,000/- (Rupees Five Thousand only). A vehicle shall be considered booked only after receipt of the booking amount by the Company.<br/><br/>
    
    <b>2. Full Payment & 30-Day Condition:</b><br/>
    After booking, the Booker must pay the full vehicle amount and take delivery within 30 (Thirty) days. If the Booker fails to complete full payment and take delivery within 30 days: Any price increase or price difference applicable at the time of delivery shall be borne entirely by the Booker.
    """
    terms_para = Paragraph(terms_text, terms_text_style)
    
    # Wrap terms in a styled table for better appearance
    terms_wrapper = Table([[terms_para]], colWidths=[7.5*inch])
    terms_wrapper.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9f9f9')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#333333')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d0d0d0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(terms_wrapper)
    elements.append(Spacer(1, 0.15*inch))
    
    # Authorization
    auth_text = f"{user.get_full_name() or user.username}, {company_name}<br/>"
    auth_text += "Authorized Signature: ________________________________________________"
    auth_para = Paragraph(auth_text, normal_style)
    elements.append(auth_para)
    
    # Build PDF
    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)
    
    # Get PDF content
    pdf_content = buffer.getvalue()
    buffer.close()
    
    # Create ContentFile
    filename = f"receipt_{booking.booking_number}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return ContentFile(pdf_content, name=filename)

