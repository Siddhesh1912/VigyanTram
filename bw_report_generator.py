from flask import send_file, session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
import os
from datetime import datetime

def generate_bw_report(product_results, compliance_table, compliance_score, uploaded_file, processed_file):
    pdf_path = "static/violation_report_bw.pdf"
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    # Border
    c.setStrokeColor(colors.black)
    c.setLineWidth(2)
    c.rect(10, 10, width-20, height-20, stroke=1, fill=0)

    # Header
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, height-45, "Violation Report")
    c.setFont("Helvetica", 11)
    c.drawString(width-220, height-45, f"Date: {datetime.now().strftime('%d-%m-%Y')}  Time: {datetime.now().strftime('%H:%M:%S')}")

    # Images Section
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, height-100, "Result Images:")
    c.setLineWidth(1)
    c.rect(40, height-320, 250, 180, stroke=1, fill=0)
    c.rect(320, height-320, 250, 180, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(110, height-135, "Captured Image")
    c.drawString(390, height-135, "Processed Image")
    if os.path.exists(uploaded_file):
        c.drawImage(uploaded_file, 40, height-320, width=250, height=180, preserveAspectRatio=True, mask='auto')
    if os.path.exists(processed_file):
        c.drawImage(processed_file, 320, height-320, width=250, height=180, preserveAspectRatio=True, mask='auto')

    # Compliance Info Table
    info_label_y = height-420
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, info_label_y, "Compliance Info Table:")
    table_y = info_label_y - 10 - (24 * len(compliance_table))
    table = Table(compliance_table, colWidths=[180, 100, 170])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.white),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN',(0,0),(-1,-1),'LEFT'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.lightgrey]),
        ('TEXTCOLOR', (1,1), (1,-1), colors.black),
    ]))
    table.wrapOn(c, width, height)
    table.drawOn(c, 40, table_y)

    # Compliance Score Box (below table, centered, black/white)
    score_box_w = 200
    score_box_h = 65
    score_box_x = width/2 - score_box_w/2
    score_box_y = table_y - score_box_h - 20
    c.setFillColor(colors.black)
    c.roundRect(score_box_x, score_box_y, score_box_w, score_box_h, 14, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(score_box_x + score_box_w/2, score_box_y + score_box_h/2 + 10, f"{compliance_score}%")
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(score_box_x + score_box_w/2, score_box_y + score_box_h/2 - 18, "Compliance Score")

    # Vigyantram stamp logo at the bottom (black/white)
    stamp_w = 150
    stamp_h = 25
    stamp_x = width/2 - stamp_w/2
    stamp_y = 25
    c.setFillColor(colors.black)
    c.roundRect(stamp_x, stamp_y, stamp_w, stamp_h, 20, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(stamp_x + stamp_w/2, stamp_y + 32, "Vigyantram")
    c.setFont("Helvetica", 11)
    c.drawCentredString(stamp_x + stamp_w/2, stamp_y + 14, "© Vigyantram Team")

    c.save()
    return pdf_path
